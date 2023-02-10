import calicam.logger
logger = calicam.logger.get(__name__)

from pathlib import Path

import cv2
import numpy as np

from calicam.cameras.synchronizer import Synchronizer
from itertools import combinations
from queue import Queue

class OmniFrameBuilder:
    def __init__(self, synchronizer: Synchronizer, single_frame_height=250):
        self.synchronizer = synchronizer 
        self.single_frame_height = single_frame_height
        self.board_count_target = 50  # used to determine sort order. Should this be in the stereo_tracker?

        self.rotation_counts = {}
        for port, stream in self.synchronizer.streams.items():
            # override here while testing this out with pre-recorded video
            self.rotation_counts[port] = 0 # stream.camera.rotation_count

        self.pairs = self.get_pairs()

        self.board_counts = {pair: 0 for pair in self.pairs} # TODO: part of future refactor to get way from stereotracker
        self.omni_list = self.pairs.copy()
        self.new_sync_packet_notice = Queue()
        self.synchronizer.subscribe_to_notice(self.new_sync_packet_notice)
        
        
    def get_pairs(self):
        pairs = [pair for pair in combinations(ports, 2)]
        sorted_ports = [
            (min(pair), max(pair)) for pair in pairs
        ]  # sort as in (b,a) --> (a,b)
        sorted_ports = sorted(
            sorted_ports
        )  # sort as in [(b,c), (a,b)] --> [(a,b), (b,c)]
        return sorted_ports

    def get_new_raw_frames(self):
        self.new_sync_packet_notice.get()
        self.current_sync_packet = self.synchronizer.current_sync_packet

        # update the board_counts here
        # TODO: will need to sort this out later...board history is throwing
        # things off to integrate old methods. Ignore for now and refactor
        # for pair in self.board_counts.keys():
        #     capture_history = self.stereo_tracker.stereo_inputs[pair]
        #     self.board_counts[pair] = len(capture_history["common_board_loc"])

    def update_omni_list(self):
        self.omni_list = [
            key
            for key, value in self.board_counts.items()
            if value < self.board_count_target
        ]
        self.omni_list = sorted(self.omni_list, key=self.board_counts.get, reverse=True)

    def get_frame_or_blank(self, port):
        """Synchronization issues can lead to some frames being None among
        the synched frames, so plug that with a blank frame"""

        edge = self.single_frame_height
        frame_packet = self.current_sync_packet.frame_packets[port]
        if frame_packet is None:
            logger.debug("plugging blank frame data")
            frame = np.zeros((edge, edge, 3), dtype=np.uint8)
        else:
            frame = frame_packet.frame

        # frame = frame.copy()
        return frame

    def draw_common_corner_current(self, frameA, portA, frameB, portB):
        """Return unaltered frame if no corner information detected, otherwise
        return two frames with same corners drawn"""
        if self.current_sync_packet.frame_packets[portA] is None:
            logger.warn(f"Dropped frame at port {portA}")
            return frameA, frameB

        elif self.current_sync_packet.frame_packets[portB] is None:
            logger.warn(f"Dropped frame at port {portB}")
            return frameA, frameB

        frame_packet_A = self.current_sync_packet.frame_packets[portA]
        frame_packet_B = self.current_sync_packet.frame_packets[portB]

        if frame_packet_A.points is None or frame_packet_B.points is None:
            return frameA, frameB
        else:
            ids_A = frame_packet_A.points.point_id
            ids_B = frame_packet_B.points.point_id
            common_ids = np.intersect1d(ids_A, ids_B)

            img_loc_A = frame_packet_A.points.img_loc
            img_loc_B = frame_packet_B.points.img_loc

            for _id, img_loc in zip(ids_A, img_loc_A):
                if _id in common_ids:
                    x = round(float(img_loc[0, 0]))
                    y = round(float(img_loc[0, 1]))

                    cv2.circle(frameA, (x, y), 5, (0, 0, 220), 3)

            for _id, img_loc in zip(ids_B, img_loc_B):
                if _id in common_ids:
                    x = round(float(img_loc[0, 0]))
                    y = round(float(img_loc[0, 1]))

                    cv2.circle(frameB, (x, y), 5, (0, 0, 220), 3)
            return frameA, frameB

    def draw_common_corner_history(self, frameA, portA, frameB, portB):
        ### TODO: Part of next round of refactor...
        pair = (portA, portB)
        img_loc_A = self.stereo_tracker.stereo_inputs[pair]["img_loc_A"]
        img_loc_B = self.stereo_tracker.stereo_inputs[pair]["img_loc_B"]

        for cornerset in img_loc_A:
            for corner in cornerset:
                corner = (int(corner[0][0]), int(corner[0][1]))
                cv2.circle(frameA, corner, 2, (255, 165, 0), 2, 1)

        for cornerset in img_loc_B:
            for corner in cornerset:
                corner = (int(corner[0][0]), int(corner[0][1]))
                cv2.circle(frameB, corner, 2, (255, 165, 0), 2, 1)

        return frameA, frameB

    def resize_to_square(self, frame):
        """To make sure that frames align well, scale them all to thumbnails
        squares with black borders."""
        logger.debug("resizing square")

        frame = cv2.flip(frame, 1)

        height = frame.shape[0]
        width = frame.shape[1]

        padded_size = max(height, width)

        height_pad = int((padded_size - height) / 2)
        width_pad = int((padded_size - width) / 2)
        pad_color = [0, 0, 0]

        logger.debug("about to pad border")
        frame = cv2.copyMakeBorder(
            frame,
            height_pad,
            height_pad,
            width_pad,
            width_pad,
            cv2.BORDER_CONSTANT,
            value=pad_color,
        )

        frame = resize(frame, new_height=self.single_frame_height)
        return frame


    def apply_rotation(self, frame, port):
        rotation_count = self.rotation_counts[port]
        if rotation_count == 0:
            pass
        elif rotation_count in [1, -3]:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rotation_count in [2, -2]:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif rotation_count in [-1, 3]:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        return frame

    def hstack_frames(self, pair, board_count):
        """place paired frames side by side with an info box to the left"""

        portA, portB = pair
        logger.debug("Horizontally stacking paired frames")
        frameA = self.get_frame_or_blank(portA)
        frameB = self.get_frame_or_blank(portB)

        # this will be part of next round of refactor
        # frameA, frameB = self.draw_common_corner_history(frameA, portA, frameB, portB)
        # frameA, frameB = self.draw_common_corner_current(frameA, portA, frameB, portB)

        frameA = self.resize_to_square(frameA)
        frameB = self.resize_to_square(frameB)

        frameA = self.apply_rotation(frameA, portA)
        frameB = self.apply_rotation(frameB, portB)

        label_display = np.zeros(
            (self.single_frame_height, int(self.single_frame_height / 2), 3), np.uint8
        )
        label_display = cv2.putText(
            label_display,
            f"{pair[0]} & {pair[1]}",
            (10, int(self.single_frame_height / 3)),
            fontFace=cv2.FONT_HERSHEY_SIMPLEX,
            fontScale=1,
            color=(255, 165, 0),
            thickness=1,
        )

        label_display = cv2.putText(
            label_display,
            str(board_count),
            (10, int(self.single_frame_height * (2 / 3))),
            fontFace=cv2.FONT_HERSHEY_SIMPLEX,
            fontScale=1,
            color=(255, 165, 0),
            thickness=1,
        )

        hstacked_pair = np.hstack((label_display, frameA, frameB))

        return hstacked_pair


    def get_completion_frame(self):
        height = int(self.single_frame_height)
        # because the label box to the left is half of the single frame width
        width = int(self.single_frame_height * 2.5)

        blank = np.zeros((height, width, 3), np.uint8)

        blank = cv2.putText(
            blank,
            "DATA COLLECTION COMPLETE",
            (20, int(self.single_frame_height / 2)),
            fontFace=cv2.FONT_HERSHEY_SIMPLEX,
            fontScale=1,
            color=(255, 165, 0),
            thickness=1,
        )
        
        return blank
    
    def get_omni_frame(self):
        """
        This glues together the stereopairs with summary blocks of the common board count
        """
        omni_frame = None
        board_target_reached = False
        for pair in self.omni_list:

            # figure out if you need to update the omni frame list
            board_count = self.board_counts[pair]
            if board_count > self.board_count_target - 1:
                board_target_reached = True

            if omni_frame is None:
                omni_frame = self.hstack_frames(pair, board_count)
            else:
                omni_frame = np.vstack(
                    [omni_frame, self.hstack_frames(pair, board_count)]
                )

        if board_target_reached:
            self.update_omni_list()

        if omni_frame is None:
            omni_frame = self.get_completion_frame()
            self.stereo_tracker.stop_event.set()
        return omni_frame


def resize(image, new_height):
    (current_height, current_width) = image.shape[:2]
    ratio = new_height / float(current_height)
    dim = (int(current_width * ratio), new_height)
    resized = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)
    return resized


if __name__ == "__main__":
    from calicam.calibration.corner_tracker import CornerTracker
    from calicam.calibration.stereotracker import StereoTracker
    from calicam.calibration.charuco import Charuco
    from calicam.recording.recorded_stream import RecordedStreamPool,RecordedStream

    logger.debug("Test live stereocalibration processing")

    repo = Path(str(Path(__file__)).split("calicam")[0], "calicam")
    recording_directory = Path(repo, "sessions", "5_cameras", "recording")

    # ports = [0, 1, 2, 3, 4]
    ports = [1,2, 3]
    charuco = Charuco(
        4, 5, 11, 8.5, aruco_scale=0.75, square_size_overide_cm=5.25, inverted=True
    )

    trackr = CornerTracker(charuco)
    recorded_stream_pool = RecordedStreamPool(ports, recording_directory, tracker=trackr)
    logger.info("Creating Synchronizer")
    syncr = Synchronizer(recorded_stream_pool.streams, fps_target=None)
    recorded_stream_pool.play_videos()

    logger.info("Creating Stereotracker")
    # stereo_tracker = StereoTracker(syncr)
    frame_builder = OmniFrameBuilder(synchronizer=syncr)

    # recorder.start_recording(recording_path)
    # while len(stereo_cal.uncalibrated_pairs) == 0:
    # time.sleep(.1)
    logger.info("Showing Paired Frames")
    while not syncr.stop_event.is_set():
        # wait for newly processed frame to be available
        # frame_ready = frame_builder.stereo_calibrator.cal_frames_ready_q.get()
        frame_builder.get_new_raw_frames()

        omni_frame = frame_builder.get_omni_frame()
        if omni_frame is None:
            cv2.destroyAllWindows()
            break

        cv2.imshow("omni frame", omni_frame)

        key = cv2.waitKey(1)

        if key == ord("q"):
            cv2.destroyAllWindows()
            break
        
    # recorder.stop_recording()
    cv2.destroyAllWindows()
