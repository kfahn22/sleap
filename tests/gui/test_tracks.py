from sleap.gui.tracks import TrackColorManager, TrackTrailManager
from sleap.io.video import Video

def test_track_trails(centered_pair_predictions):
    
    labels = centered_pair_predictions
    trail_manager = TrackTrailManager(labels=labels, scene=None, trail_length = 5)
    
    frames = trail_manager.get_frame_selection(27)
    assert len(frames) == 5
    assert frames[0].frame_idx == 22
    
    tracks = trail_manager.get_tracks_in_frame(27)
    assert len(tracks) == 2
    assert tracks[0].name == "1"
    assert tracks[1].name == "2"

    trails = trail_manager.get_track_trails(frames, tracks[0])
    
    assert len(trails) == 24
    
    test_trail = [
        (222.0, 205.0),
        (222.0, 203.0),
        (223.0, 203.0),
        (225.0, 201.0),
        (226.0, 199.0)
        ]
    assert test_trail in trails
    
    # Test track colors
    color_manager = TrackColorManager(labels=labels)

    tracks = trail_manager.get_tracks_in_frame(1099)
    assert len(tracks) == 5

    assert color_manager.get_color(tracks[3]) == [119, 172, 48]