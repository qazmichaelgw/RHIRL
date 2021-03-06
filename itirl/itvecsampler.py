# AUTOGENERATED! DO NOT EDIT! File to edit: 04_ITVecSampler.ipynb (unless otherwise specified).

__all__ = ['update_scene', 'plot_animation', 'ITVectorizedSampler']

# Cell
import matplotlib
import matplotlib.animation as animation
import matplotlib.pyplot as plt
plt.rcParams['axes.labelsize'] = 14
plt.rcParams['xtick.labelsize'] = 12
plt.rcParams['ytick.labelsize'] = 12
# export
def update_scene(num, frames, patch):
    patch.set_data(frames[num])
    return patch,

def plot_animation(frames, repeat=False, interval=40):
    plt.close()  # or else nbagg sometimes plots in the previous cell
    fig = plt.figure()
    patch = plt.imshow(frames[0])
    plt.axis('off')
    return animation.FuncAnimation(fig, update_scene, fargs=(frames, patch), frames=len(frames), repeat=repeat, interval=interval)

# Cell
import pickle

import tensorflow as tf
from rllab.sampler.base import BaseSampler
from sandbox.rocky.tf.envs.parallel_vec_env_executor import ParallelVecEnvExecutor
from sandbox.rocky.tf.envs.vec_env_executor import VecEnvExecutor
from rllab.misc import special
from rllab.misc import tensor_utils
import numpy as np
from rllab.sampler.stateful_pool import ProgBarCounter
import rllab.misc.logger as logger
import itertools
import sys
from ctypes import *
import os
from scipy.signal import savgol_filter
import time

from numba import jit

class ITVectorizedSampler(BaseSampler):
    """
    Information theoratic vectorized sampler
    """

    def __init__(self, algo, n_envs=None, parallel=True):
        super(ITVectorizedSampler, self).__init__(algo)
        self.n_envs = n_envs
        self.inverse_lambda = 1.0 / self.algo.irl_model.lbda
        self.parallel = parallel
        self.discount_factor = self.algo.discount ** np.arange(0, self.algo.max_path_length)
        print ('inverse_lambda', self.inverse_lambda, 'discount', self.algo.discount)
        # mark whether reset when training
        self.good_itr = True
        self.last_sample_reward = 0

    def start_worker(self, n_parallel):
        n_envs = self.n_envs
        if n_envs is None:
            n_envs = self.algo.batch_size
            n_envs = max(1, min(n_envs, 100))
        print ('n_envs', n_envs, self.algo.env.type_status)

        if getattr(self.algo.env, 'vectorized', False):
            self.vec_env = self.algo.env.vec_env_executor(n_envs=n_envs, max_path_length=self.algo.max_path_length)
        else:
            if self.parallel:
                self.vec_env = ParallelVecEnvExecutor(
                    env = self.algo.env,
                    n = n_envs,
                    max_path_length = self.algo.max_path_length,
                    n_parallel=min(n_envs, n_parallel),
                )
            else:
                envs = [pickle.loads(pickle.dumps(self.algo.env)) for _ in range(n_envs)]
                for env in envs:
                    env.type_status=self.algo.env.type_status
                self.vec_env = VecEnvExecutor(
                    envs=envs,
                    max_path_length=self.algo.max_path_length
                )

        self.env_spec = self.algo.env.spec
        # update n_envs
        self.n_envs = n_envs
        self.init_obses = None

    def shutdown_worker(self):
        self.vec_env.terminate()

    def reset_to_state(self, init_state, obs):
        """
        reset environment to a specific state.
        """
        # print ("trigger reset to state")
        if self.parallel:
#             print ("here")
            dummpy_obs = self.vec_env.reset()
#             print ("here 2")
            self.vec_env.reset_to_state(init_state, obs)
            self.init_state = init_state
            self.obs = obs
            self.init_obses = [obs for env in range(self.n_envs)]
        # print ('reset to state', init_state, obs, actions)
        # first reset all other related variales by calling reset
        else:
            dummpy_obs = self.vec_env.reset()
            self.init_state = init_state
            self.obs = obs
            for env in self.vec_env.envs:
                self.algo.set_env_state(init_state, env)
#                 state = env.wrapped_env.env.state
#                 memmove(state.ctypes.data, init_state.ctypes.data, state_size)
            self.init_obses = [obs for env in self.vec_env.envs]

    def eval(self, itr, env, state, obs, nominal_control, num_steps, is_training, with_true_weights, discount, num_trials=3):
        backup_nominal_control = self.algo.policy.nominal_control
        # evaluate the performance of the learned reward given the current nominal control
        reward = np.zeros((num_trials, num_steps))
        init_state = state
        init_obs = obs
        for n in range(num_trials):
            #reset control
            self.algo.policy.update_nominal_control(nominal_control)
            #reset state
            dummpy_obs = env.reset()
            self.algo.set_env_state(init_state, env)
#             memmove(env.wrapped_env.env.state.ctypes.data, init_state.ctypes.data, state_size)
            state = init_state
            obs = init_obs

            # for saving videos only
            frames = []
            # for expert recording sampling
            experts = {"traj":[]}
            traj = {"observations":[]}

            if num_steps == -1:
                while True:
                    #for _ in range(4):
                    new_control = self.fast_sampling_and_processing(t, state, obs, with_true_weights, is_training=False)
                    self.algo.policy.update_nominal_control(new_control + self.algo.policy.nominal_control)
                    action = self.algo.policy.get_current_control()
                    obs, rwd, done, info = env.step(action)
                    #state = env.wrapped_env.env.state
                    state = self.algo.get_env_state(env)
                    reward[n, t] = rwd
                    self.algo.policy.elapse_one_step()
                    if done:
                        break
            else:
                times = np.zeros(num_steps)
                for t in range(num_steps):
                    last = time.time()
                    #for _ in range(4):
                    # skip render if with true weights to save time
                    new_control = self.fast_sampling_and_processing(t, state, obs, with_true_weights, is_training=False)
                    self.algo.policy.update_nominal_control(new_control + self.algo.policy.nominal_control)
                    action = self.algo.policy.get_current_control()
                    obs, rwd, done, info = env.step(action)
                    env.render()
                    rgb = env.wrapped_env.env.render('rgb_array')
                    frames.append(rgb)
                    traj["observations"].append(np.reshape(obs, (-1)))
                    print ("current action", action)
                    print (f'itr {itr} steps {t} reward {rwd} reward so far {np.mean(reward[:n+1, :t+1].sum(axis=1))} done {done} progress {float(t)/num_steps*100}%')
                    #state = env.wrapped_env.env.state
                    state = self.algo.get_env_state(env)
                    reward[n, t] = rwd
                    self.algo.policy.elapse_one_step()
                    if done:
                        break
                    times[t] = time.time() - last
                    last = time.time()
                    print ('estimated total time(mins)', np.mean(times[:t+1])*num_steps/60, "remaining (mins)", np.mean(times[:t+1])*(num_steps-t)/60)
            if with_true_weights:
                traj["observations"] = np.array(traj["observations"])
                experts['traj'].append(traj)
                expert_fn = os.path.join(logger.get_snapshot_dir(), f'expert_{itr}.pickle')
                with open(expert_fn, "wb") as f:
                    pickle.dump(experts, f, protocol=4)
            # print ("here")
            fn = os.path.join(logger.get_snapshot_dir(), f'eval_{itr}_train_{is_training}_groundtruth_{with_true_weights}.mp4')
            video = plot_animation(frames)
            # Set up formatting for the movie files
            Writer = animation.writers['ffmpeg']
            writer = Writer(fps=15, metadata=dict(artist='Me'), bitrate=1800)
            print (f"Saving evaluation video to {fn}")
            video.save(fn, writer=writer)
        # restore nominal control
        self.algo.policy.update_nominal_control(backup_nominal_control)
        # undiscounted reward
        undiscounted_reward = np.mean(reward.sum(axis=1))
        discounted_reward = np.mean(np.dot(reward, discount ** np.arange(0, num_steps)))

        print (f'iter {itr} discounted_reward', discounted_reward)
        print (f'iter {itr} undiscounted_reward', undiscounted_reward)
        logger.record_tabular('Iteration', itr)
        logger.record_tabular('AverageDiscountedReturn', discounted_reward)
        logger.record_tabular('AverageReturn', undiscounted_reward)
        fn = os.path.join(logger.get_snapshot_dir(), f'eval_{itr}_train_{is_training}_groundtruth_{with_true_weights}.pkl')
        res = [undiscounted_reward, discounted_reward]
        with open(fn, 'wb') as f:
            pickle.dump(res, f)

    def fast_expert_sampling(self, init_state, obs, policy, num_paths):
        #only call once to generate expert data
        self.reset_to_state(init_state, obs)
        obses = self.init_obses
        n_trajs = 0
        path_obs_shape = (num_paths, self.algo.max_path_length) + self.vec_env.observation_space.shape
        path_obs = np.zeros(path_obs_shape)
        path_reward = np.zeros((num_paths, self.algo.max_path_length, 1))
        path_valids = np.zeros((num_paths, self.algo.max_path_length, 1), dtype=np.uint8)
        trigger_valids = np.ones(num_paths, dtype=np.uint8)
        cur_step = 0

        while n_trajs < num_paths:
            next_n_trajs = min(n_trajs+self.n_envs, num_paths)
            actions, agent_infos = policy.get_actions(obses)
            next_obses, rewards, dones, env_infos = self.vec_env.step(actions)
            np_obs = np.array(obses)[:next_n_trajs-n_trajs]
            np_rewards = np.array(rewards)[:next_n_trajs-n_trajs]

            # store info
            path_reward[n_trajs:next_n_trajs, cur_step, 0] = np_rewards
            path_obs[n_trajs:next_n_trajs, cur_step, :] = np_obs
            trigger_valids[n_trajs:next_n_trajs] = (1-dones)[:next_n_trajs-n_trajs]*trigger_valids[n_trajs:next_n_trajs]
            path_valids[n_trajs:next_n_trajs, cur_step, 0] = trigger_valids[n_trajs:next_n_trajs]

            # update state
            cur_step += 1
            obses = next_obses
            #print ('dones', cur_step, dones, rewards, trigger_valids)
            if trigger_valids[n_trajs:next_n_trajs].sum() == 0:
                self.reset_to_state(init_state, obs)
                obses = self.init_obses
                n_trajs = next_n_trajs
                cur_step=0

        # here, must change the first False valids to true, otherwise, it will
        # miss the reward of first done, which is significant in most sparse reward tasks.
        index = path_valids.sum(axis=1)[:, 0]
        index = np.vstack((np.arange(num_paths), index, [0]*num_paths)).astype(np.uint8)
        path_valids[index[0], index[1], index[2]] = 1

        return path_obs, path_valids

    # @jit()
    def fast_sampling_and_processing(self, itr, init_state, obs, with_true_weights=False, is_training=False):
        # fast implementation of sampling and post processing
        self.reset_to_state(init_state, obs)
        # print state
        #print ('state', self.vec_env.get_state())

        n_trajs = 0
        obses = self.init_obses
        policy = self.algo.policy
        paths = []
        cur_step = 0

        # maintain sampling info
        path_control_cost = np.zeros((self.algo.batch_size, self.algo.max_path_length, 1))
        path_xi = np.zeros((self.algo.batch_size, self.algo.max_path_length, self.vec_env.action_space.flat_dim))
        path_obs_shape = (self.algo.batch_size, self.algo.max_path_length) + self.vec_env.observation_space.shape
        path_obs = np.zeros(path_obs_shape)
        path_reward = np.zeros((self.algo.batch_size, self.algo.max_path_length, 1))
        path_valids = np.zeros((self.algo.batch_size, self.algo.max_path_length, 1), dtype=np.uint8)
        trigger_valids = np.ones(self.algo.batch_size, dtype=np.uint8)
        while n_trajs < self.algo.batch_size:
            # print (f"n_trajs {n_trajs} cur_step {cur_step}")
            next_n_trajs = min(n_trajs+self.n_envs, self.algo.batch_size)
            policy.update_idx(cur_step, n_trajs)
            actions, agent_infos = policy.get_actions(obses)
            next_obses, rewards, dones, env_infos = self.vec_env.step(actions)
            np_obs = np.array(obses)[:next_n_trajs-n_trajs]
#             print ("N_trajs", n_trajs)
#             import cv2
#             for idx in range(len(np_obs)):
#                 cv2.imshow(f"np_obs{idx}", np_obs[idx])
#                 cv2.waitKey(1)
            np_rewards = np.array(rewards)[:next_n_trajs-n_trajs]
            np_control_cost = np.array(agent_infos['control_cost'])[:next_n_trajs-n_trajs]
            # print (actions.shape, np_control_cost.shape)
            # if self.algo.env.type_status == "CarRacing":
            #     np_control_cost += (actions[:, 2]*actions[:,2] - actions[:, 1]*actions[:, 1])
            np_xi = np.array(agent_infos['xi'])[:next_n_trajs-n_trajs]

            # store info
            path_control_cost[n_trajs:next_n_trajs, cur_step, 0] = np_control_cost
            path_reward[n_trajs:next_n_trajs, cur_step, 0] = np_rewards
            path_xi[n_trajs:next_n_trajs, cur_step, :] = np_xi
            path_obs[n_trajs:next_n_trajs, cur_step, :] = np_obs
#             for idx in range(len(np_obs)):
#                 cv2.imshow(f"path_obs{idx}", path_obs[n_trajs+idx, cur_step].astype(np.uint8))
#                 cv2.waitKey(1)
#             print (path_obs.shape)
            trigger_valids[n_trajs:next_n_trajs] = (1-dones)[:next_n_trajs-n_trajs]*trigger_valids[n_trajs:next_n_trajs]
            path_valids[n_trajs:next_n_trajs, cur_step, 0] = trigger_valids[n_trajs:next_n_trajs]
            #print ('trigger', trigger_valids, cur_step, path_valids)

            # update state
            cur_step += 1
            obses = next_obses
            #print ('dones', cur_step, dones, rewards, trigger_valids)
            if trigger_valids[n_trajs:next_n_trajs].sum() == 0:
                self.reset_to_state(init_state, obs)
                obses = self.init_obses
                n_trajs = next_n_trajs
                cur_step=0

# debug use
#         import cv2
#         print ("Path Obs", path_obs.shape)
#         for i in range(len(path_obs)):
#             for j in range(path_obs[i,:,:].shape[0]):
#                 cv2.imshow(f"Sample{i}", path_obs[i,j])
#                 cv2.waitKey(1)
#             cv2.waitKey(10)
#             print ('path', i, len(path_obs[i,:,:]))
#             print ("Sampled", path_obs[i,:, :].shape)
#             print (path_reward[i,:, :])
#             print ('valids', path_valids[i,:, :])

        # here, must change the first False valids to true, otherwise, it will
        # miss the reward of first done, which is significant in most sparse reward tasks.
        index = path_valids.sum(axis=1)[:, 0]
        index = np.vstack((np.arange(self.algo.batch_size), index, [0]*self.algo.batch_size)).astype(np.uint8)
        path_valids[index[0], index[1], index[2]] = 1

        if with_true_weights:
            # calculate weights
            weights = -path_reward + path_control_cost
            #only consider valid paths
            weights = weights*path_valids
            weights = np.dot(weights[:,:,0], self.discount_factor)
            weights -= weights.min()
            weights = np.exp(-self.inverse_lambda * weights)
            weights /= weights.sum()
            print ("weights", weights, weights.shape, weights.sum())
        elif is_training:
            weights = self.algo.irl_model.fit(path_obs, path_control_cost, path_valids, self.algo.lr, self.algo.discount, itr)
        else:
            weights = self.algo.irl_model.eval(path_obs, path_control_cost, path_valids, self.algo.discount)

        discounted_reward = np.mean(np.dot(path_reward[:,:,0], self.discount_factor))
        undiscounted_reward = np.mean(np.sum(path_reward, axis=1))
        logger.record_tabular('Iteration', itr)
        logger.record_tabular('(OpenLoopReward not treat it seriously. Only Evaluation is valid) SamplingAverageReturn', undiscounted_reward)
        if undiscounted_reward == self.last_sample_reward:
            print ("reach a local minimal")
            self.good_itr = False
        else:
            self.good_itr = True
        self.last_sample_reward = undiscounted_reward

        new_control = np.dot(path_xi.T, weights).T
        # add filter here
        #new_control = savgol_filter(new_control, 29, 5, axis=0)
        if self.algo.env.type_status == 'classic':
            new_control = savgol_filter(new_control, 11, 3, axis=0)
        else:
            new_control = savgol_filter(new_control, 29, 5, axis=0)
        return new_control

    def obtain_samples(self, itr):
        logger.log("Obtaining samples for iteration %d..." % itr)
        paths = []
        # redefine the meaning of n_samples to n_trajs for information theoratic approach
        # n_samples = 0
        n_trajs = 0
        # reset to the same starting state
        obses=self.init_obses
        dones = np.asarray([True] * self.vec_env.num_envs)
        running_paths = [None] * self.vec_env.num_envs

        pbar = ProgBarCounter(self.algo.batch_size)
        policy_time = 0
        env_time = 0
        process_time = 0
        cur_step = 0

        policy = self.algo.policy
        import time
        while n_trajs < self.algo.batch_size:
            t = time.time()
            policy.reset(dones)
            policy.update_idx(cur_step, n_trajs)
            actions, agent_infos = policy.get_actions(obses)

            policy_time += time.time() - t
            t = time.time()
            next_obses, rewards, dones, env_infos = self.vec_env.step(actions)
            cur_step += 1
            env_time += time.time() - t

            t = time.time()

            agent_infos = tensor_utils.split_tensor_dict_list(agent_infos)
            env_infos = tensor_utils.split_tensor_dict_list(env_infos)
            if env_infos is None:
                env_infos = [dict() for _ in range(self.vec_env.num_envs)]
            if agent_infos is None:
                agent_infos = [dict() for _ in range(self.vec_env.num_envs)]
            for idx, observation, action, reward, env_info, agent_info, done in zip(itertools.count(), obses, actions,
                                                                                    rewards, env_infos, agent_infos,
                                                                                    dones):
                if running_paths[idx] is None:
                    running_paths[idx] = dict(
                        observations=[],
                        actions=[],
                        rewards=[],
                        env_infos=[],
                        agent_infos=[],
                    )
                running_paths[idx]["observations"].append(observation)
                # sampling actions, and env_infos are not needed in our approach
                #running_paths[idx]["actions"].append(action)
                #running_paths[idx]["env_infos"].append(env_info)
                running_paths[idx]["rewards"].append(reward)
                running_paths[idx]["agent_infos"].append(agent_info)
                if done:
                    paths.append(dict(
                        observations=self.env_spec.observation_space.flatten_n(running_paths[idx]["observations"]),
                        #actions=self.env_spec.action_space.flatten_n(running_paths[idx]["actions"]),
                        #env_infos=tensor_utils.stack_tensor_dict_list(running_paths[idx]["env_infos"]),
                        rewards=tensor_utils.stack_tensor_list(running_paths[idx]["rewards"]),
                        agent_infos=tensor_utils.stack_tensor_dict_list(running_paths[idx]["agent_infos"]),
                    ))
                    n_trajs += 1
                    cur_step = 0
                    running_paths[idx] = None
                    # reset env
                    self.reset_to_state(self.init_state, self.obs)
                    next_obses = self.init_obses
            process_time += time.time() - t
            pbar.inc(n_trajs)
            obses = next_obses

        pbar.stop()

        logger.record_tabular("PolicyExecTime", policy_time)
        logger.record_tabular("EnvExecTime", env_time)
        logger.record_tabular("ProcessExecTime", process_time)

        return paths

    def process_samples(self, itr, paths, with_weights=False):
        # with_weights: Whether calculate importance weights from groud truth reward
        # transfer to from numpy to tensors
        for idx, path in enumerate(paths):
            path["returns"] = special.discount_cumsum(path["rewards"], self.algo.discount)
            # should be cost instead of rewards
            if with_weights:
                path["weight"] = special.discount_cumsum(-path["rewards"]+path["agent_infos"]["control_cost"], self.algo.discount)[0]

        max_path_length = max([len(path["observations"]) for path in paths])
        # make all paths the same length (pad extra advantages with 0)
        obs = [path["observations"] for path in paths]
        obs = tensor_utils.pad_tensor_n(obs, max_path_length)

        #actions = [path["actions"] for path in paths]
        #actions = tensor_utils.pad_tensor_n(actions, max_path_length)

        # no need to maintain this for saving computation powers
        #rewards = [path["rewards"] for path in paths]
        #rewards = tensor_utils.pad_tensor_n(rewards, max_path_length)

        #returns = [path["returns"] for path in paths]
        #returns = tensor_utils.pad_tensor_n(returns, max_path_length)

        # update importance weights
        if with_weights:
            weights = [path["weight"] for path in paths]
            weights = tensor_utils.stack_tensor_list(weights)
            # minus the minimal trajectory cost
            weights -= weights.min()
            weights = np.exp(-self.inverse_lambda * weights)
            weights /= weights.sum()
            # print ("weights", weights, weights.shape, weights.sum())
        else:
            weights = None

        agent_infos = [path["agent_infos"] for path in paths]
        agent_infos = tensor_utils.stack_tensor_dict_list(
            [tensor_utils.pad_tensor_dict(p, max_path_length) for p in agent_infos]
        )

        #env_infos = [path["env_infos"] for path in paths]
        #env_infos = tensor_utils.stack_tensor_dict_list(
        #    [tensor_utils.pad_tensor_dict(p, max_path_length) for p in env_infos]
        #)

        valids = [np.ones_like(path["returns"]) for path in paths]
        valids = tensor_utils.pad_tensor_n(valids, max_path_length)

        average_discounted_return = \
            np.mean([path["returns"][0] for path in paths])

        undiscounted_returns = [sum(path["rewards"]) for path in paths]

        samples_data = dict(
            observations=obs,
            #actions=actions,
            #rewards=rewards,
            #returns=returns,
            valids=valids,
            agent_infos=agent_infos,
            #env_infos=env_infos,
            weights=weights,
            paths=paths,
        )

        logger.record_tabular('Iteration', itr)
        logger.record_tabular('AverageDiscountedReturn',
                              average_discounted_return)
        logger.record_tabular('AverageReturn', np.mean(undiscounted_returns))
        logger.record_tabular('NumTrajs', len(paths))
        logger.record_tabular('StdReturn', np.std(undiscounted_returns))
        logger.record_tabular('MaxReturn', np.max(undiscounted_returns))
        logger.record_tabular('MinReturn', np.min(undiscounted_returns))

        return samples_data
