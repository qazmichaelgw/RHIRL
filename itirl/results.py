# AUTOGENERATED! DO NOT EDIT! File to edit: 14_results.ipynb (unless otherwise specified).

__all__ = ['smooth', 'plot_ablation', 'plot_results', 'METHODS', 'NAME', 'SAMPLES_PER_ITER']

# Cell
from .lunarlander import register as lunarlander_register
from .bipedalwalker import register as biepdalwalker_register
from .carracing import register as carracing_register
lunarlander_register()
biepdalwalker_register()
carracing_register()

# Cell
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tqdm import tqdm
from sandbox.rocky.tf.envs.base import TfEnv
from rllab.envs.gym_env import GymEnv
from rllab.envs.noisy_env import NoisyActionEnv
from scipy import stats

METHODS = ["ITIRL", "TRPO", "Random", "AIRL", "GAIL"]
NAME={
    "pendulum":"Pendulum-v0",
    "lunarlander":"LunarLanderContinuous-v2",
    "bipedalwalker":"BipedalWalker-v2",
    'carracing': "CarRacing-v0",
}

SAMPLES_PER_ITER={
    NAME["pendulum"]:{
        'ITIRL': 60000,
        'ITIRL_TwoLoop10': 200000,
        'ITIRL_TwoLoop100': 400000,
        'AIRL':10000,
        'GAIL':10000,
        "TRPO":60000,
        "Random":60000,
    },
    NAME["lunarlander"]:{
        'ITIRL': 8000,
        'AIRL':10000,
        'GAIL':10000,
        "TRPO":10000,
        "Random":10000,
    },
    NAME["bipedalwalker"]:{
        'ITIRL': 40000,
        'AIRL':50000,
        'GAIL':50000,
        "TRPO":50000,
        "Random":50000,
    },
}

def smooth(a, df):
    return a.rolling(window=max(1,int(0.05*df.shape[0])), min_periods=1, center=True).mean().values.flatten()

def plot_ablation(name, base_dir, noise, path_length=100, with_step_size=True):
    methods = ["ITIRL", "TRPO", "Random", "ITIRL_TwoLoop10", "ITIRL_TwoLoop100"]
    n = 3
    lasts = 100
    trpo = pd.read_csv(f"{base_dir}/{name}/{name}_noise{noise}/progress.csv")
    itirl = pd.read_csv(f"{base_dir}/{name}/{name}_itirl_noise{noise}/train_True_groundtruth_False_progress.csv")
    itirl_twoloop10 = pd.read_csv(f"{base_dir}/{name}/{name}_itirl_noise{noise}/train_True_groundtruth_False_progress_10.csv")
    itirl_twoloop100 = pd.read_csv(f"{base_dir}/{name}/{name}_itirl_noise{noise}/train_True_groundtruth_False_progress_100.csv")

    df = pd.DataFrame(columns=methods)
    iters = itirl['Iteration']
    values = itirl['AverageReturn']
    df[methods[0]] = np.interp(np.arange(lasts*n), iters, values)
    df[methods[1]] = np.repeat(trpo['AverageReturn'].values[-lasts:], n)
    iters = itirl_twoloop10['Iteration']
    values = itirl_twoloop10['AverageReturn']
    df[methods[3]] = np.interp(np.arange(lasts*n), iters, values)
    iters = itirl_twoloop100['Iteration']
    values = itirl_twoloop100['AverageReturn']
    df[methods[4]] = np.interp(np.arange(lasts*n), iters, values)

    # random performance run
    env = TfEnv(NoisyActionEnv(GymEnv(NAME[name], record_video=False, record_log=False), act_noise=noise))
    rwd = np.zeros((lasts*n, path_length))
    for i in tqdm(range(lasts*n)):
        obs = env.reset()
        for t in range(path_length):
            action = env.action_space.sample()
            obs, reward, done, info = env.step(action)
            rwd[i,t] = reward
            if done:
                break
    rwd = np.sum(rwd, axis=1)
    df[methods[2]] = rwd

    for i in range(len(methods)):
        df[methods[i]] = smooth(df[methods[i]], df)

    # report last 20 iteration performance in table.
    results = {}
    for i in range(len(methods)):
        results[methods[i]] = np.mean(df[methods[i]][-20:])
        results[f'{methods[i]}_err'] = stats.sem(df[methods[i]][-20:])
    print (results)

    fig, ax = plt.subplots()

    for idx, col in enumerate(df.columns):
        data = df[col].values
        #ax = data.plot(ax=ax,kind ='line', x=df.index*SAMPLES_PER_ITER[NAME[name]][methods[idx]], y=col,  label=col)
        if with_step_size:
            x = df.index*SAMPLES_PER_ITER[NAME[name]][methods[idx]]
        else:
            x = df.index
        #ax = data.plot(ax=ax,kind ='line', x=x, y=col)
        ax.plot(x, data, label=col)
#     step_size = np.min(list(SAMPLES_PER_ITER[NAME[name]].values()))
#     print (step_size)
#     min_index = df.index[-1]*step_size
#     print (min_index)
    if with_step_size:
        plt.xlim(20000, 60000*300)
        #plt.legend(loc='best')
        plt.legend(loc='lower right')
        ax.set_xlabel("Number of interactive samples", fontsize=20)
        ax.set_ylabel("Original Trajectory Reward", fontsize=20)
        plt.title(f"{name} Noise {noise}", fontsize=20)
        plt.tight_layout()
        plt.savefig(f"./Ablation_{name}_noise{noise}.png")
    else:
        plt.legend(loc='lower right')
        ax.set_xlabel("Number of outer loops", fontsize=20)
        ax.set_ylabel("Original Trajectory Reward", fontsize=20)
        plt.title(f"{name} Noise {noise}", fontsize=20)
        plt.tight_layout()
        plt.savefig(f"./AblationOuterLoop_{name}_noise{noise}.png")
    plt.show()

def plot_results(name, base_dir, noise, path_length=100):

    methods = METHODS
    # we only consider the last few iterations as the experts from trpo
    # so we here only plot the last a few iterations of trpo performance.
    lasts = 100
    trpo = pd.read_csv(f"{base_dir}/{name}/{name}_noise{noise}/progress.csv")
    itirl = pd.read_csv(f"{base_dir}/{name}/{name}_itirl_noise{noise}/train_True_groundtruth_False_progress.csv")
#     itirl = pd.read_csv(f"{base_dir}/{name}/{name}_itirl_noise{noise}/train_True_groundtruth_True_progress.csv")
    #gcl = pd.read_csv(f"{base_dir}/{name}/{name}_gcl_noise{noise}/progress.csv")
    airl = pd.read_csv(f"{base_dir}/{name}/{name}_airl_noise{noise}/progress.csv")
    gail = pd.read_csv(f"{base_dir}/{name}/{name}_gail_noise{noise}/progress.csv")

    df = pd.DataFrame(columns=methods)
    iters = itirl['Iteration']
    values = itirl['AverageReturn']
    df[methods[0]] = np.interp(np.arange(airl.shape[0]), iters, values)
    df[methods[1]] = np.repeat(trpo['AverageReturn'].values[-lasts:], airl.shape[0]/lasts)

    # random performance run
    env = TfEnv(NoisyActionEnv(GymEnv(NAME[name], record_video=False, record_log=False), act_noise=noise))
    rwd = np.zeros((airl.shape[0], path_length))
    for i in tqdm(range(airl.shape[0])):
        obs = env.reset()
        for t in range(path_length):
            action = env.action_space.sample()
            obs, reward, done, info = env.step(action)
            rwd[i,t] = reward
            if done:
                break
    rwd = np.sum(rwd, axis=1)
    df[methods[2]] = rwd
    df[methods[3]] = airl['OriginalTaskAverageReturn']
    df[methods[4]] = gail['OriginalTaskAverageReturn']

    for i in range(len(methods)):
        df[methods[i]] = smooth(df[methods[i]], df)

    # report last 20 iteration performance in table.
    results = {}
    for i in range(len(methods)):
        results[methods[i]] = np.mean(df[methods[i]][-20:])
        results[f'{methods[i]}_err'] = stats.sem(df[methods[i]][-20:])
    print (results)

    fig, ax = plt.subplots()

    for idx, col in enumerate(df.columns):
        data = df[col].values
        #ax = data.plot(ax=ax,kind ='line', x=df.index*SAMPLES_PER_ITER[NAME[name]][methods[idx]], y=col,  label=col)
        x = df.index*SAMPLES_PER_ITER[NAME[name]][methods[idx]]
        #ax = data.plot(ax=ax,kind ='line', x=x, y=col)
        label=col
        if col == "ITIRL":
            label=f"$I^2RL$"
        ax.plot(x, data, label=label)
    step_size = np.min(list(SAMPLES_PER_ITER[NAME[name]].values()))
    print (step_size)
    min_index = df.index[-1]*step_size
    print (min_index)
    plt.xlim(step_size, min_index)
    #plt.legend(loc='best')
    plt.legend(loc='lower right')
    ax.set_xlabel("Number of interactive samples", fontsize=20)
    ax.set_ylabel("Original Trajectory Reward", fontsize=20)
    plt.title(f"{name} Noise {noise}", fontsize=20)
    plt.tight_layout()
    plt.savefig(f"./{name}_noise{noise}.png")
    plt.show()

plot_ablation("pendulum", '~/ownCloud/itirl_results', noise=0.5, with_step_size=True)
