import os
import pickle

import cv2
import numpy as np
from tqdm import tqdm

from mmhuman3d.data.data_converters.builder import DATA_CONVERTERS
from mmhuman3d.data.data_structures.human_data import HumanData
from .base_converter import BaseModeConverter


@DATA_CONVERTERS.register_module()
class Pw3dConverter(BaseModeConverter):

    ACCEPTED_MODES = ['train', 'test']

    def __init__(self, modes=[]):
        super(Pw3dConverter, self).__init__(modes)

    def bbox_expand(self, bbox_xywh, scale_factor=1.2):
        center = [
            bbox_xywh[0] + bbox_xywh[2] / 2, bbox_xywh[1] + bbox_xywh[3] / 2
        ]
        x = scale_factor * (bbox_xywh[0] - center[0]) + center[0]
        y = scale_factor * (bbox_xywh[1] - center[1]) + center[1]
        w = bbox_xywh[2] * scale_factor * scale_factor
        h = bbox_xywh[3] * scale_factor * scale_factor
        return [x, y, w, h]

    def convert_by_mode(self, dataset_path, out_path, mode):
        # use HumanData to store all data
        human_data = HumanData()

        # structs we use
        image_path_, bbox_xywh_ = [], []
        smpl = {}
        smpl['body_pose'] = []
        smpl['global_orient'] = []
        smpl['betas'] = []
        meta = {}
        meta['gender'] = []

        # get a list of .pkl files in the directory
        dataset_path = os.path.join(dataset_path, 'sequenceFiles', mode)
        files = [
            os.path.join(dataset_path, f) for f in os.listdir(dataset_path)
            if f.endswith('.pkl')
        ]

        # go through all the .pkl files
        for filename in tqdm(files):
            with open(filename, 'rb') as f:
                data = pickle.load(f, encoding='latin1')
                smpl_pose = data['poses']
                smpl_betas = data['betas']
                poses2d = data['poses2d']
                global_poses = data['cam_poses']
                genders = data['genders']
                valid = np.array(data['campose_valid']).astype(np.bool)
                num_people = len(smpl_pose)
                num_frames = len(smpl_pose[0])
                seq_name = str(data['sequence'])
                img_names = np.array([
                    'imageFiles/' + seq_name +
                    '/image_%s.jpg' % str(i).zfill(5)
                    for i in range(num_frames)
                ])
                # get through all the people in the sequence
                for i in range(num_people):
                    valid_pose = smpl_pose[i][valid[i]]
                    valid_betas = np.tile(smpl_betas[i][:10].reshape(1, -1),
                                          (num_frames, 1))
                    valid_betas = valid_betas[valid[i]]
                    valid_keypoints_2d = poses2d[i][valid[i]]
                    valid_img_names = img_names[valid[i]]
                    valid_global_poses = global_poses[valid[i]]
                    gender = genders[i]
                    # consider only valid frames
                    for valid_i in range(valid_pose.shape[0]):
                        keypoints2d = valid_keypoints_2d[valid_i, :, :].T
                        keypoints2d = keypoints2d[keypoints2d[:, 2] > 0, :]
                        bbox_xywh = [
                            min(keypoints2d[:, 0]),
                            min(keypoints2d[:, 1]),
                            max(keypoints2d[:, 0]) - min(keypoints2d[:, 0]),
                            max(keypoints2d[:, 1]) - min(keypoints2d[:, 0])
                        ]
                        bbox_xywh = self.bbox_expand(bbox_xywh)

                        # transform global pose
                        pose = valid_pose[valid_i]
                        extrinsics = valid_global_poses[valid_i][:3, :3]
                        pose[:3] = cv2.Rodrigues(
                            np.dot(extrinsics,
                                   cv2.Rodrigues(pose[:3])[0]))[0].T[0]

                        image_path_.append(valid_img_names[valid_i])
                        bbox_xywh_.append(bbox_xywh)
                        smpl['body_pose'].append(pose[3:].reshape((23, 3)))
                        smpl['global_orient'].append(pose[:3])
                        smpl['betas'].append(valid_betas[valid_i])
                        meta['gender'].append(gender)

        # change list to np array
        bbox_xywh_ = np.array(bbox_xywh_).reshape((-1, 4))
        bbox_xywh_ = np.hstack([bbox_xywh_, np.ones([bbox_xywh_.shape[0], 1])])
        smpl['body_pose'] = np.array(smpl['body_pose']).reshape((-1, 23, 3))
        smpl['global_orient'] = np.array(smpl['global_orient']).reshape(
            (-1, 3))
        smpl['betas'] = np.array(smpl['betas']).reshape((-1, 10))
        meta['gender'] = np.array(meta['gender'])

        human_data['image_path'] = image_path_
        human_data['bbox_xywh'] = bbox_xywh_
        human_data['smpl'] = smpl
        human_data['meta'] = meta
        human_data['config'] = '3dpw'

        # store data
        if not os.path.isdir(out_path):
            os.makedirs(out_path)

        file_name = '3dpw_{}.npz'.format(mode)
        out_file = os.path.join(out_path, file_name)
        human_data.dump(out_file)