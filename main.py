import argparse
from pathlib import Path
import yaml
from  datetime import datetime

from logging import getLogger

import torch
import torch.nn as nn
import torch.optim as optim
import torchvision.transforms as transforms
import torchvision.datasets as datasets

from tensorboardX import SummaryWriter
from torchsummary import summary

from utils.path_process import Paths
from utils.dataset import make_datapath_list
from utils.dataset import DataTransforms, Dataset
from utils.plot_cmx import plot_confusion_matrix
from utils.setup_logger import setup_logger
from models.generalizer import Generalizer
from models.metrics.metrics import Metrics
from models.networks.network import AutoEncoder

logger = getLogger(__name__)

def parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--configfile', type=str, default='./configs/default.yml')
    parser.add_argument("--inference", action="store_true", default=False)
    args = parser.parse_args()
    return args

def main():
    args = parser()

    ### setup configs ###
    configfile = args.configfile

    with open(configfile) as f:
        configs = yaml.load(f)

    ## path process (path definition, make directories)
    now = datetime.now().isoformat()
    log_dir = Path(configs['log_dir']) / now
    paths = Paths(log_dir=log_dir)

    ### setup logs and summary writer ###
    setup_logger(logfile=paths.logfile)

    writer = SummaryWriter(str(paths.summary_dir))

    ### setup GPU or CPU ###
    if configs['n_gpus'] > 0 and torch.cuda.is_available():
        logger.info('CUDA is available! using GPU...\n')
        device = torch.device('cuda')
    else:
        logger.info('using CPU...\n')
        device = torch.device('cpu')

    ### Dataset ###
    logger.info('preparing dataset...')

    train_transform = DataTransforms(img_size=configs['img_size'], color_mean=configs['color_mean'], color_std=configs['color_std'], phase='train')
    test_transform = DataTransforms(img_size=configs['img_size'], color_mean=configs['color_mean'], color_std=configs['color_std'], phase='test')
    train_img_list, test_img_list = make_datapath_list(root=configs['data_root'])
    train_dataset = Dataset(train_img_list, transform=train_transform)
    test_dataset = Dataset(test_img_list, transform=test_transform)
  
    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=configs['batch_size'], shuffle=True, num_workers=8)
    test_loader = torch.utils.data.DataLoader(test_dataset, batch_size=configs['batch_size'], shuffle=False, num_workers=8)

    ### Network ###
    logger.info('preparing network...')

    network = AutoEncoder(in_channels=configs['n_channels'])

    network = network.to(device)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(network.parameters(), lr=configs['lr'])

    if configs['resume']:
        # Load checkpoint
        logger.info('==> Resuming from checkpoint...\n')
        if not Path(configs['resume']).exists():
            logger.info('No checkpoint found !')
            raise ValueError('No checkpoint found !')

        ckpt = torch.load(configs['resume'])
        network.load_state_dict(ckpt['model_state_dict'])
        optimizer.load_state_dict(ckpt['optimizer_state_dict'])
        start_epoch = ckpt['epoch']
        loss = ckpt['loss']
    else:
        logger.info('==> Building model...\n')
        start_epoch = 0

    logger.info('model summary: ')
    summary(network, input_size=(configs['n_channels'], configs['img_size'], configs['img_size']))

    if configs["n_gpus"] > 1:
        network = nn.DataParallel(network)

    ### Metrics ###
    metrics = Metrics(writer=writer, metrics_dir=paths.metrics_dir)

    ### Train or Test ###
    kwargs = {
        'device': device,
        'network': network,
        'optimizer': optimizer,
        'criterion': criterion,
        'data_loaders': (train_loader, test_loader),
        'metrics': metrics,
        'writer': writer,
        'save_ckpt_interval': configs['save_ckpt_interval'],
        'ckpt_dir': paths.ckpt_dir,
        'img_outdir': paths.img_outdir,
    }

    generalizer = Generalizer(**kwargs)

    if args.inference:
        if not configs['resume']:
            logger.info('No checkpoint found for inference!')
        logger.info('mode: inference\n')
        generalizer.test(epoch=start_epoch, inference=True)
    else:
        logger.info('mode: train\n')
        generalizer.train(n_epochs=configs['n_epochs'], start_epoch=start_epoch)

if __name__ == "__main__":
    main()