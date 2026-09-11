"""What RDX's own mix analysis would say about a rendered file.

    .venv/bin/python scripts/render/measure.py artifacts/renders/trance.wav

Integrated loudness, peak, crest, clipped samples, the share of energy in each
band, and the verdicts rdx/musical/mixdown.py would reach from them — so a
change to a preset, a patch or the master chain can be judged by the same
thresholds RDX uses on the user's own mixes, and in the same words.
"""
import sys, wave
import numpy as np
from rdx.musical import mixdown

for path in sys.argv[1:]:
    with wave.open(path) as w:
        rate, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        st = (np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768).reshape(-1, ch)
    mono = st.mean(axis=1)
    lufs = mixdown.loudness(mono, rate)
    peak = float(np.abs(st).max())
    rms = float(np.sqrt((mono ** 2).mean()))
    energies, total = mixdown.band_energy(mono, rate)
    share = mixdown.shares(energies, total)
    L = mixdown.LIMITS
    bottom = share["sub"] + share["low"]
    verdicts = []
    if lufs < L["quiet"]: verdicts.append(f"QUIET ({lufs:.1f} < {L['quiet']})")
    if lufs > L["loudness"]: verdicts.append(f"LOUD ({lufs:.1f} > {L['loudness']})")
    if share["mud"] > L["mud_share"]: verdicts.append(f"MUDDY (mud {share['mud']:.0%} > {L['mud_share']:.0%})")
    if bottom + share["mud"] > L["low_share"]: verdicts.append(f"BOOMY (<400Hz {bottom + share['mud']:.0%} > {L['low_share']:.0%})")
    if bottom < L["bottom_thin"]: verdicts.append("THIN")
    if share["high"] > L["high_share"]: verdicts.append("HARSH")
    if share["air"] < L["air_thin"]: verdicts.append(f"CLOSED IN (air {share['air']:.2%} < {L['air_thin']:.1%})")
    crest = 20 * np.log10(peak / max(rms, 1e-12))
    if crest < L["crest"]: verdicts.append(f"SQUASHED (crest {crest:.1f} < {L['crest']})")
    name = path.split("/")[-1]
    print(f"{name:16} {lufs:6.1f} LUFS  peak {20*np.log10(peak+1e-12):5.1f}  crest {crest:4.1f}  clipped {int((np.abs(st)>=0.999).sum())}")
    print(f"{'':16} " + "  ".join(f"{k} {v:.0%}" for k, v in share.items()))
    print(f"{'':16} RDX would say: {'; '.join(verdicts) or 'nothing wrong'}")
