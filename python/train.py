
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt
import tensorflow as tf

from ca_model import CAModel
from io_helpers import *


class Trainer():
    def __init__(self, ca, target, batch_size=9, pool_size=512, target_padding=16, damage_n=3):
        self.ca = ca
        self.target = target
        self.batch_size = batch_size
        self.pool_size = pool_size
        self.damage_n = damage_n

        p = target_padding
        self.target = tf.pad(self.target, [(p, p), (p, p), (0, 0)])
        self.h, self.w = self.target.shape[:2]
        self.seed = np.zeros([self.h, self.w, 16], np.float32)
        self.seed[self.h // 2, self.w // 2, 3:] = 1.
        
        self.pool = np.repeat(self.seed[np.newaxis, ...], pool_size, 0)
        self.loss_log = []

        lr = 2e-3
        lr_sched = tf.keras.optimizers.schedules.PiecewiseConstantDecay(
            [2000], [lr, lr * 0.1])
        self.optimizer = tf.keras.optimizers.Adam(lr_sched)
    
    @tf.function
    def make_circle_masks(self, n, h, w):
        x = tf.linspace(-1.0, 1.0, w)[None, None, :]
        y = tf.linspace(-1.0, 1.0, h)[None, :, None]
        center = tf.random.uniform([2, n, 1, 1], -0.5, 0.5)
        r = tf.random.uniform([n, 1, 1], 0.1, 0.4)
        x, y = (x - center[0]) / r, (y - center[1]) / r
        mask = tf.cast(x * x + y * y < 1.0, tf.float32)
        return mask
    
    def loss_fn(self, x):
        return tf.reduce_mean(tf.square(x[..., :4] - self.target), [-2, -3, -1])
    
    @tf.function
    def train_step(self, x):
        iter_n = tf.random.uniform([], 16, 32, tf.int32)
        with tf.GradientTape() as g:
            for i in tf.range(iter_n):
                x = self.ca(x)
            loss = tf.reduce_mean(self.loss_fn(x))
        grads = g.gradient(loss, self.ca.weights)
        grads = [g / (tf.norm(g) + 1e-8) for g in grads]
        self.optimizer.apply_gradients(zip(grads, self.ca.weights))
        return x, loss

    def step(self):
        # sample pool
        batch_idx = np.random.choice(self.pool_size, self.batch_size, replace=False)
        batch_x = self.pool[batch_idx]
        # sort by initial loss (high to low)
        loss_rank = self.loss_fn(batch_x).numpy().argsort()[::-1]
        batch_x = batch_x[loss_rank]
        # reset example with max loss
        batch_x[0] = self.seed
        # damage last n examples (lowest loss)
        if self.damage_n > 0:
            damage_mask = self.make_circle_masks(self.damage_n, self.h, self.w).numpy()[..., np.newaxis]
            batch_x[-self.damage_n:] *= 1.0 - damage_mask

        x2, loss = self.train_step(batch_x)

        self.pool[batch_idx] = x2
        loss = loss.numpy()
        self.loss_log.append(loss)
        return x2
    
    def plot_loss(self, path):
        plt.figure(figsize=(10, 4))
        plt.title('Loss history (log10)')
        plt.plot(np.log10(self.loss_log), '.', alpha=0.1)
        plt.savefig(path)


if __name__ == '__main__':
    ca = CAModel()
    target = load_image('../gfx/mock_small.png')
    trainer = Trainer(ca, target)
    h, w = trainer.h, trainer.w

    for i in tqdm(range(4000 + 1)):
        x2 = trainer.step()
        if i % 200 == 0:
            imgs = x2[:9, ..., :4].numpy()
            output_3x3 = imgs.reshape(3, 3, h, w, 4).swapaxes(
                1, 2).reshape(h * 3, w * 3, 4)
            save_image('train_output/out_{}.png'.format(i), output_3x3)
            trainer.plot_loss('train_output/loss.png')
            print(' step: {}, log10(loss): {:.4f}'.format(i, np.log10(np.mean(trainer.loss_log[-200:]))))
            ca.model.save('train_output/model.h5')
            serialize_lua('train_output/weights.lua', ca)
