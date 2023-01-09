import glob

import torch
import segmentation_models_pytorch as smp
import albumentations as A
from albumentations.pytorch import ToTensorV2
import cv2
from mmseg.models import build_segmentor
from mmcv.runner.optimizer import build_optimizer
from .utils import select_device
from .metrics import AverageMeter
import os
# config
# ===============================================================================
use_wandb = True
wandb_key = "d0ee13baa7af4379eff80e68b11cf976bbb8d673"
wandb_project = "Polyp-Research"
wandb_entity = "ssl-online"
wandb_name = "RLP (1)"
wandb_group = "RLP B4"
wandb_dir = "./wandb"

seed = 2022
device = "cuda:0" if torch.cuda.is_available() else 'cpu'
num_workers = 8

train_images = glob.glob('/home/nguyen.van.quan/scatsimclr/TrainDataset/image/*')
train_masks = [i.replace('image', 'mask') for i in train_images]

test_folder = "/home/nguyen.van.quan/scatsimclr/TestDataset"
test_images = glob.glob(f'{test_folder}/*/images/*')
test_masks = glob.glob(f'{test_folder}/*/masks/*')

save_path = "runs/test"

image_size = 352

bs = 16
bs_val = 2
grad_accumulate_rate = 1

train_loss_meter = AverageMeter()
iou_meter = AverageMeter()
dice_meter = AverageMeter()

n_eps = 50
save_ckpt_ep = n_eps-5
val_ep = n_eps
best = -1.

init_lr = 1e-4

focal_loss = smp.losses.FocalLoss(smp.losses.BINARY_MODE)
dice_loss = smp.losses.DiceLoss(smp.losses.BINARY_MODE)
bce_loss = smp.losses.SoftBCEWithLogitsLoss()
loss_fns = [bce_loss, dice_loss]
loss_weights = [0.8, 0.2]

train_transform = A.Compose([
    A.HorizontalFlip(p=0.5),
    A.VerticalFlip(p=0.5),
    A.RandomGamma (gamma_limit=(50, 150), eps=None, always_apply=False, p=0.5),
    A.RandomBrightness(p=0.3),
    A.RGBShift(p=0.3, r_shift_limit=5, g_shift_limit=5, b_shift_limit=5),
    A.OneOf([A.Blur(), A.GaussianBlur(), A.GlassBlur(), A.MotionBlur(), A.GaussNoise(), A.Sharpen(), A.MedianBlur(), A.MultiplicativeNoise()]),
    A.Cutout(p=0.3, max_h_size=25, max_w_size=25, fill_value=255),
    A.ShiftScaleRotate(p=0.3, border_mode=cv2.BORDER_CONSTANT, shift_limit=0.15, scale_limit=0.11),
    A.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    ToTensorV2(),
])

val_transform = A.Compose([
    A.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    ToTensorV2(),
])

def segformer(arch):
    num_layers = []
    pretrained = f'pretrained/mit_{arch}_mmseg.pth'
    if arch == 'b1':
        num_layers = [2,2,2,2]
    if arch == 'b2':
        num_layers = [3, 4, 6, 3 ]
    if arch == 'b3':
        num_layers = [3, 4, 18, 3]
    if arch == 'b4':
        num_layers = [3, 8, 27, 3]
    model = dict(
        type='SunSegmentor',
        backbone=dict(
            type='MixVisionTransformer',
            in_channels=3,
            embed_dims=64,
            num_stages=4,
            num_layers=num_layers,
            num_heads=[1, 2, 5, 8],
            patch_sizes=[7, 3, 3, 3],
            sr_ratios=[8, 4, 2, 1],
            out_indices=(0, 1, 2, 3),
            mlp_ratio=4,
            qkv_bias=True,
            drop_rate=0.0,
            attn_drop_rate=0.0,
            drop_path_rate=0.1,
            pretrained=pretrained),
        decode_head=dict(
            type='DRPHead',
            in_channels=[64, 128, 320, 512],
            in_index=[0, 1, 2, 3],
            channels=128,
            dropout_ratio=0.1,
            num_classes=1,
            norm_cfg=dict(type='BN', requires_grad=True),
            align_corners=False,
            loss_decode=dict(type='CrossEntropyLoss', use_sigmoid=True, loss_weight=1.0)),
        # model training and testing settings
        train_cfg=dict(),
        test_cfg=dict(mode='whole'))
    model = build_segmentor(model)
    model.init_weights()
    return model

# ===============================================================================