from PIL import Image


def frame_duration_ms(fps):
    return max(1, int(round(1000 / fps)))


def estimate_gif_bytes(width, height, fps, duration):
    """Poids maximum : une image différente à chaque pas, sur toute la durée."""
    frames = max(1, int(round(float(duration) * float(fps))))
    pixels = max(0, int(width)) * max(0, int(height))
    return pixels * frames + 1024


def _palette(frames):
    sample_count = min(len(frames), 16)
    step = max(1, len(frames) // sample_count)
    chosen = frames[::step][:sample_count]
    thumb = 80
    sheet = Image.new("RGB", (thumb * len(chosen), thumb))
    for index, frame in enumerate(chosen):
        sheet.paste(frame.resize((thumb, thumb), Image.Resampling.BILINEAR), (index * thumb, 0))
    return sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT)


def write_gif(frames, path, fps):
    if not frames:
        raise RuntimeError("Aucune image à encoder.")
    rgb = [frame.convert("RGB") for frame in frames]
    palette = _palette(rgb)
    converted = [
        frame.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
        for frame in rgb
    ]
    converted[0].save(
        path,
        save_all=True,
        append_images=converted[1:],
        duration=frame_duration_ms(fps),
        loop=0,
        optimize=False,
        disposal=1,
    )
