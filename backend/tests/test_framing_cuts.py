"""Enquadramento: troca de câmera, salto confirmado e "quem fala" normalizado por pessoa."""
from app.pipeline import framing


def test_camera_snaps_on_scene_cut_instead_of_panning():
    fps = 6.0
    times = [i / fps for i in range(36)]
    targets = [0.3] * 18 + [0.75] * 18                 # o rosto troca de lugar aos 3 s
    pan = framing.smooth_path(times, targets, 0.32, fps, initial=0.3)
    snap = framing.smooth_path(times, targets, 0.32, fps, initial=0.3, cuts=[3.0])
    at = dict(snap)
    assert abs(at[3.0] - 0.75) < 1e-6                   # na troca de câmera: direto no rosto
    assert abs(dict(pan)[3.0] - 0.3) < 0.05             # sem a troca detectada: ainda longe (panorâmica)


def test_single_detector_glitch_does_not_move_camera():
    fps = 6.0
    times = [i / fps for i in range(30)]
    targets = [0.3] * 30
    targets[10] = targets[11] = 0.8                     # dois quadros de detecção errada
    path = framing.smooth_path(times, targets, 0.32, fps, initial=0.3)
    assert max(abs(x - 0.3) for _, x in path) < 0.02
    targets = [0.3] * 10 + [0.8] * 20                   # mudança real (se mantém): segue
    path = framing.smooth_path(times, targets, 0.32, fps, initial=0.3)
    assert path[-1][1] > 0.7


def test_scene_cut_detection():
    diffs = [(i / 6, 3.0 + (i % 3)) for i in range(60)]
    diffs[20] = (20 / 6, 60.0)
    diffs[45] = (45 / 6, 12.0)                          # movimento forte, mas não troca de câmera
    assert framing.scene_cuts(diffs) == [20 / 6]
    assert framing.scene_cuts(diffs[:2]) == []


def test_speaker_choice_is_normalized_per_person():
    times = [i / 6 for i in range(120)]
    near, far = framing.Track(), framing.Track()
    near.points = [(t, 0.3, 0.4, 0.2, 0.3) for t in times]
    far.points = [(t, 0.75, 0.4, 0.1, 0.15) for t in times]
    for i, t in enumerate(times):
        talking_far = 60 <= i < 120                     # na 2ª metade quem fala é a pessoa de longe
        near.motion[t] = 6.0 + (1.0 if not talking_far else 0.0) + (i % 2) * 0.2   # sempre "mexe" mais (perto)
        far.motion[t] = 1.0 + (2.0 if talking_far else 0.0) + (i % 2) * 0.1
    out = framing._speaker_targets(times, [near, far])
    assert out[30][1] == 0.3                            # 1ª metade: pessoa de perto
    assert out[-1][1] == 0.75                           # 2ª metade: a de longe, mesmo com menos movimento bruto
    switches = sum(1 for a, b in zip(out, out[1:]) if a[1] != b[1])
    assert switches == 1                                # sem vai-e-volta
