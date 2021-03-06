# AUTOGENERATED! DO NOT EDIT! File to edit: 02_model.ipynb (unless otherwise specified).

__all__ = ['conv2d', 'maxpool2d', 'leaky_relu', 'conv_net', 'ITIRL_Net', 'dropout']

# Cell
import tensorflow as tf
import numpy as np
from airl.models.architectures import relu_net
from airl.utils.hyperparametrized import Hyperparametrized
from airl.models.imitation_learning import ImitationLearning
from rllab.misc import tensor_utils
from rllab.misc import special
from airl.models.tf_util import discounted_reduce_sum
import joblib
import pickle

# Cell
dropout = 0.75 # Dropout, probability to keep units
#wrappers for convnet
def conv2d(x, W, b, strides=1):
    # Conv2D wrapper, with bias and relu activation
    x = tf.nn.conv2d(x, W, strides=[1, strides, strides, 1], padding='SAME')
    x = tf.nn.bias_add(x, b)
    return tf.nn.relu(x)

def maxpool2d(x, k=2):
    return tf.nn.max_pool(x, ksize=[1, k, k, 1], strides=[1, k, k, 1],padding='SAME')

def leaky_relu(z):
    return np.maximum(0.01 * z, z)

def conv_net(x, weights, biases):
    x = tf.reshape(x, (-1, 96, 96, 3))

    # Convolution Layer
    conv1 = conv2d(x, weights['wc1'], biases['bc1'])
    # Max Pooling (down-sampling)
    conv1 = maxpool2d(conv1, k=2)

    # Convolution Layer
    conv2 = conv2d(conv1, weights['wc2'], biases['bc2'])
    # Max Pooling (down-sampling)
    conv2 = maxpool2d(conv2, k=2)

    # Convolution Layer
    conv3 = conv2d(conv2, weights['wc3'], biases['bc3'])
    # Max Pooling (down-sampling)
    conv3 = maxpool2d(conv3, k=2)

    # Convolution Layer
    conv4 = conv2d(conv3, weights['wc4'], biases['bc4'])
    # Max Pooling (down-sampling)
    conv4 = maxpool2d(conv4, k=2)

    # Fully connected layer
    # Reshape conv2 output to fit fully connected layer input
    fc1 = tf.reshape(conv4, [-1, weights['wd1'].get_shape().as_list()[0]])
    fc1 = tf.add(tf.matmul(fc1, weights['wd1']), biases['bd1'])
    fc1 = tf.nn.relu(fc1)
    # Apply Dropout
    fc1 = tf.nn.dropout(fc1, dropout)

    # Output, class prediction
    out = tf.add(tf.matmul(fc1, weights['out']), biases['out'])
    # normalize to (0,1 )
    # out = tf.nn.tanh(out)

    # scale to any cost function
    # out = -tf.log(out)
    # out = tf.log(out)
    return out

class ITIRL_Net(ImitationLearning):
    def __init__(self, env_spec,
                 alpha,
                 p_lambda,
                 sigma,
                 l2_reg,
                 expert_trajs=None,
                 arch=relu_net,
                 arch_args={},
                 network_type="MLP",
                 batch_size=None,
                 name="ITIRL_Net"):
        # control parameters
        # the same notations in: https://arxiv.org/pdf/1707.02342.pdf Algorithm 1
        # gamma = lambda*(1-alpha)
        # lambda == 1, by default
        self.alpha = alpha
        self.gamma = p_lambda*(1-alpha)
        self.lbda = p_lambda
        self.inverse_lambda = 1.0 / self.lbda
        self.sigma = sigma

        self.dO = env_spec.observation_space.flat_dim
        self.dU = env_spec.action_space.flat_dim
        self.network_type = network_type

        # move to method sampling
        #self.set_demos(expert_trajs)

        print (f'ITIRL Net params, alpha {alpha}, gamma {self.gamma}, lambda {self.lbda}, sigma {sigma}  network_type {network_type}.')

        # build IRL reward model
        # here the batch size is the number of trajs.
        with tf.variable_scope(name) as vs:
            # should be batch_size x T x dO

            self.act_cost = tf.placeholder(tf.float32, [None, None, 1], name='act_cost')
            self.valids = tf.placeholder(tf.float32, [None, None, 1], name='valids')
            # in our model, the cost is state cost instead of state action cost.
            #self.act_t = tf.placeholder(tf.float32, [None, None, self.dU], name='act')
            self.lr = tf.placeholder(tf.float32, (), name='lr')
            self.discount = tf.placeholder(tf.float32, (), name='discount')

            if network_type == "MLP":
                with tf.variable_scope('cost') as cvs:
                    self.obs_t = tf.placeholder(tf.float32, [None, None, self.dO], name='obs')
                    self.state_cost = arch(self.obs_t, **arch_args)
                    self.traj_cost = discounted_reduce_sum((self.state_cost+self.act_cost)*self.valids, self.discount, axis=1)
                    self.weights = self.traj_cost - tf.reduce_min(self.traj_cost)
                    self.weights = tf.exp(-self.inverse_lambda * self.weights)
                    self.weights = self.weights / tf.reduce_sum(self.weights)
                    self.theta = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=cvs.name)
            else:
                with tf.variable_scope('cost') as cvs:
                    self.obs_t = tf.placeholder(tf.float32, [None, None, 96, 96, 3], name='obs')
                    # Store layers weight & bias
                    weights = {
                        # 5x5 conv, 1 input, 32 outputs
                        'wc1': tf.Variable(tf.random_normal([3, 3, 3, 16], stddev=1e-2)),
                        # 5x5 conv, 32 inputs, 64 outputs
                        'wc2': tf.Variable(tf.random_normal([3, 3, 16, 32], stddev=1e-2)),
                        # 5x5 conv, 32 inputs, 64 outputs
                        'wc3': tf.Variable(tf.random_normal([3, 3, 32, 64], stddev=1e-2)),
                        # 5x5 conv, 32 inputs, 64 outputs
                        'wc4': tf.Variable(tf.random_normal([3, 3, 64, 128], stddev=1e-2)),
                        # fully connected, 7*7*64 inputs, 1024 outputs
                        'wd1': tf.Variable(tf.random_normal([6*6*128, 128], stddev=1e-2)),
                        # 1024 inputs, 10 outputs (class prediction)
                        'out': tf.Variable(tf.random_normal([128, 1], stddev=1e-2))
                    }

                    biases = {
                        'bc1': tf.Variable(tf.random_normal([16], stddev=1e-2)),
                        'bc2': tf.Variable(tf.random_normal([32], stddev=1e-2)),
                        'bc3': tf.Variable(tf.random_normal([64], stddev=1e-2)),
                        'bc4': tf.Variable(tf.random_normal([128], stddev=1e-2)),
                        'bd1': tf.Variable(tf.random_normal([128], stddev=1e-2)),
                        'out': tf.Variable(tf.random_normal([1], stddev=1e-2))
                    }

                    self.state_cost = conv_net(self.obs_t, weights, biases)
                    # print (self.state_cost)
                    self.state_cost = tf.reshape(self.state_cost, [batch_size, -1, 1])
                    self.traj_cost = discounted_reduce_sum((self.state_cost+self.act_cost)*self.valids, self.discount, axis=1)
                    self.weights = self.traj_cost - tf.reduce_min(self.traj_cost)
                    self.weights = tf.exp(-self.inverse_lambda * self.weights)
                    self.weights = self.weights / tf.reduce_sum(self.weights)
                    self.theta = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=cvs.name)

            self.l2_loss = tf.add_n([tf.nn.l2_loss(v) for v in self.theta])
            self.grad_l2 = tf.gradients(self.l2_loss, self.theta)
            self.expert_grad_theta = tf.gradients(self.state_cost, self.theta, self.valids)
            #self.grad_theta = tf.gradients(self.traj_cost, self.theta, -self.weights)

            self.expert_grad_theta = [tf.add(l2_reg*self.grad_l2[i], self.expert_grad_theta[i]) for i in range(len(self.grad_l2))]
            #self.grad_theta = [tf.add(l2_reg*self.grad_l2[i], self.grad_theta[i]) for i in range(len(self.grad_l2))]

            #self.grad_theta, _ = tf.clip_by_global_norm(self.grad_theta, 100.0)
            self.expert_grad_theta, _ = tf.clip_by_global_norm(self.expert_grad_theta, 10.0)
            self.optim = tf.train.AdamOptimizer(learning_rate=self.lr)
            self.expert_step = self.optim.apply_gradients(zip(self.expert_grad_theta, self.theta))
            #self.step = self.optim.apply_gradients(zip(self.grad_theta, self.theta))
            self._make_param_ops(vs)

    @staticmethod
    def extract_paths(paths, keys=('observations',)):
        key = keys[0]
        max_path_length = max([len(path[key]) for path in paths])
        valids = [np.ones(len(path[key])) for path in paths]
        # make all paths the same length (pad extra advantages with 0)
        obs = [path[key] for path in paths]
        obs = tensor_utils.pad_tensor_n(obs, max_path_length)
        valids = tensor_utils.pad_tensor_n(valids, max_path_length)
        print (valids[0])
        return obs, np.expand_dims(valids , -1)

    def fit(self, path_obs, path_control_cost, path_valids, lr, discount, itr, **kwargs):
        # cost map learning
        if self.network_type == "CONV":
            expert_full_obs, expert_full_valids = self.expert_trajs
            # print ('expert full shape', expert_full_obs.shape)
            margin = expert_full_obs.shape[1]-self.max_path_length

            start = np.random.randint(itr, margin)
            # start = itr
            # print (f"margin {margin} start_idx {start}")
            expert_obs = expert_full_obs[:, start:start+self.max_path_length, :, :, :]
            expert_valids = expert_full_valids[:, start:start+self.max_path_length, :]
            # print (expert_valids)
            # preprocess image by normalize to 0~1
            expert_obs /= 255
            path_obs /= 255
        else:
            expert_obs, expert_valids = self.expert_trajs_extracted
        print ('expert shape', expert_obs.shape)
        print ('sampling shape', path_obs.shape)
        # expert trajectory back propagate 1/N.
        _ = tf.get_default_session().run([self.expert_step],
            feed_dict={
                self.obs_t: expert_obs,
                self.discount: discount,
                self.valids: 1.0/len(expert_obs)*expert_valids,
                self.lr: lr,
            })


        print ("generate sample weights")
        weights = tf.get_default_session().run(self.weights,
            feed_dict={
                self.obs_t: path_obs,
                self.discount: discount,
                self.valids: path_valids,
                self.act_cost: path_control_cost,
            })

        print ("weights", weights.sum(), weights)
        importance_weights = -np.repeat(weights[:,np.newaxis,:], path_obs.shape[1], axis=1)*path_valids
        print ("importance weight step")
        _ = tf.get_default_session().run([self.expert_step],
            feed_dict={
                self.obs_t: path_obs,
                self.discount: discount,
                self.valids: importance_weights,
                self.lr: lr,
            })

#         _ = tf.get_default_session().run([self.expert_step, self.weights],
#             feed_dict={
#                 self.obs_t: path_obs,
#                 self.discount: discount,
#                 self.valids: path_valids,
#                 self.act_cost: path_control_cost,
#                 self.lr: lr,
#             })
        return weights[:, 0]

    def eval(self, observations, control_cost, path_valids, discount):
        # print ("eval")
        # print ("observations", observations.shape)
        # print ("discount", discount)
        # print ("valids", path_valids.shape)
        # print ("act_cost", control_cost.shape)
        #only normalize with image
#         observations /= 255

        # for debug use
        state_cost = tf.get_default_session().run(self.state_cost,
            feed_dict={
                self.obs_t: observations,
                self.discount: discount,
                self.valids: path_valids,
                self.act_cost: control_cost,
            })

        # print ("state cost", state_cost.shape)
        print ("state cost", state_cost[0])

        weights = tf.get_default_session().run(self.weights,
            feed_dict={
                self.obs_t: observations,
                self.discount: discount,
                self.valids: path_valids,
                self.act_cost: control_cost,
            })
        # print ("weights", weights[:, 0])
        # print ("after eval")
        return weights[:, 0]