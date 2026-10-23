"""
Game engine export formatters.

Converts the existing TexturePacker-compatible atlas JSON into
engine-specific formats for Godot, Unity, GameMaker, and Unreal Engine.
"""

from __future__ import annotations


def build_godot_tres(
    atlas: dict,
    texture_filename: str = "spritesheet.png",
) -> str:
    """Build a Godot SpriteFrames .tres resource from atlas JSON.

    The user saves the spritesheet PNG and this .tres file in the same
    directory, and Godot imports it as a ready-to-use SpriteFrames resource.
    """
    meta = atlas.get("meta", {})
    frames = atlas.get("frames", {})
    frame_tags = meta.get("frameTags", [])

    lines = [
        '[gd_resource type="SpriteFrames" format=3]',
        "",
        f'[ext_resource type="Texture2D" path="res://{texture_filename}" id="1"]',
        "",
        "[resource]",
    ]

    # Group frames by animation tag
    animations = {}
    if frame_tags:
        for tag in frame_tags:
            name = tag["name"]
            anim_frames = []
            frame_list = list(frames.values())
            for i in range(tag["from"], tag["to"] + 1):
                if i < len(frame_list):
                    anim_frames.append(frame_list[i])
            animations[name] = anim_frames
    else:
        # No tags — single "default" animation with all frames
        animations["default"] = list(frames.values())

    anim_entries = []
    for anim_name, anim_frames in animations.items():
        fps = 1000.0 / anim_frames[0]["duration"] if anim_frames else 8.0
        frame_defs = []
        for f in anim_frames:
            r = f["frame"]
            frame_defs.append(
                f'    {{"texture": ExtResource("1"), '
                f'"region": Rect2({r["x"]}, {r["y"]}, {r["w"]}, {r["h"]})}}'
            )

        # Sanitize animation name for Godot string literal
        safe_name = anim_name.replace("\\", "").replace('"', "").replace("&", "")
        entry = (
            f'{{"name": &"{safe_name}", '
            f'"speed": {fps:.1f}, '
            f'"loop": true, '
            f'"frames": [{", ".join(frame_defs)}]}}'
        )
        anim_entries.append(entry)

    lines.append(f"animations = [{', '.join(anim_entries)}]")
    return "\n".join(lines) + "\n"


def build_unity_anim(
    atlas: dict,
    texture_filename: str = "spritesheet.png",
) -> dict:
    """Build Unity-compatible sprite metadata with animation clip data.

    Returns a dict with sprite rects and animation clip definitions
    that can be consumed by Unity's sprite importer or custom scripts.
    """
    meta = atlas.get("meta", {})
    frames = atlas.get("frames", {})
    frame_tags = meta.get("frameTags", [])
    sheet_size = meta.get("size", {"w": 0, "h": 0})

    # Build sprite definitions
    sprites = []
    for name, frame_data in frames.items():
        r = frame_data["frame"]
        p = frame_data.get("pivot", {"x": 0.5, "y": 1.0})
        sprites.append({
            "name": name,
            "rect": {"x": r["x"], "y": r["y"], "width": r["w"], "height": r["h"]},
            "pivot": {"x": p["x"], "y": p["y"]},
        })

    # Build animation clips
    clips = []
    if frame_tags:
        frame_list = list(frames.keys())
        for tag in frame_tags:
            clip_frames = []
            for i in range(tag["from"], tag["to"] + 1):
                if i < len(frame_list):
                    f = list(frames.values())[i]
                    clip_frames.append({
                        "sprite": frame_list[i],
                        "time": (i - tag["from"]) * f["duration"] / 1000.0,
                    })
            clips.append({
                "name": tag["name"],
                "loop": True,
                "frames": clip_frames,
            })

    return {
        "texture": texture_filename,
        "textureSize": {"width": sheet_size["w"], "height": sheet_size["h"]},
        "sprites": sprites,
        "animationClips": clips,
    }


def build_gamemaker_yy(
    atlas: dict,
    texture_filename: str = "spritesheet.png",
    sprite_name: str = "spr_retrogaze",
) -> dict:
    """Build a GameMaker-compatible sprite definition from atlas JSON.

    Returns a dict matching GameMaker's .yy sprite resource format.
    GameMaker imports this alongside the spritesheet PNG to create a
    ready-to-use sprite resource with animation frames.
    """
    meta = atlas.get("meta", {})
    frames = atlas.get("frames", {})
    frame_tags = meta.get("frameTags", [])
    sheet_size = meta.get("size", {"w": 0, "h": 0})

    # GameMaker frames: each frame references a region of the spritesheet
    gm_frames = []
    for i, (name, frame_data) in enumerate(frames.items()):
        r = frame_data["frame"]
        gm_frames.append({
            "compositeImage": {
                "FrameId": {"name": name, "path": f"sprites/{sprite_name}/{sprite_name}.yy"},
                "LayerId": None,
                "resourceType": "GMSpriteBitmap",
            },
            "FrameId": i,
            "x": r["x"],
            "y": r["y"],
            "w": r["w"],
            "h": r["h"],
        })

    # Determine frame dimensions from first frame
    first_frame = list(frames.values())[0]["frame"] if frames else {"w": 16, "h": 16}
    origin_x = first_frame["w"] // 2
    origin_y = first_frame["h"]  # bottom-center default

    # Build animation sequences from frame tags
    sequences = []
    if frame_tags:
        for tag in frame_tags:
            seq_frames = []
            for i in range(tag["from"], tag["to"] + 1):
                frame_list = list(frames.values())
                if i < len(frame_list):
                    f = frame_list[i]
                    seq_frames.append({
                        "frame": i,
                        "duration": f["duration"] / 1000.0,
                    })
            sequences.append({
                "name": tag["name"],
                "loop": True,
                "frames": seq_frames,
            })

    return {
        "resourceType": "GMSprite",
        "name": sprite_name,
        "width": first_frame["w"],
        "height": first_frame["h"],
        "origin": {"x": origin_x, "y": origin_y},
        "textureFile": texture_filename,
        "textureSize": {"width": sheet_size["w"], "height": sheet_size["h"]},
        "frames": gm_frames,
        "sequences": sequences,
        "nineSlice": None,
        "playbackSpeed": 8.0,
        "playbackSpeedType": 0,
    }


def build_unreal_sprite(
    atlas: dict,
    texture_filename: str = "spritesheet.png",
    asset_name: str = "S_Retrogaze",
) -> dict:
    """Build Unreal Engine Paper2D-compatible sprite data from atlas JSON.

    Returns a dict with sprite definitions and flipbook animation data
    that can be imported into Unreal's Paper2D system. Each frame becomes
    a sprite, and frame tags become flipbook animations.
    """
    meta = atlas.get("meta", {})
    frames = atlas.get("frames", {})
    frame_tags = meta.get("frameTags", [])
    sheet_size = meta.get("size", {"w": 0, "h": 0})

    # Build individual sprite definitions (one per frame)
    sprites = []
    for name, frame_data in frames.items():
        r = frame_data["frame"]
        p = frame_data.get("pivot", {"x": 0.5, "y": 1.0})
        sprites.append({
            "name": f"{asset_name}_{name}",
            "sourceTexture": texture_filename,
            "sourceUV": {"x": r["x"], "y": r["y"]},
            "sourceDimension": {"x": r["w"], "y": r["h"]},
            "pivot": {"x": p["x"], "y": p["y"]},
        })

    # Build flipbook definitions from frame tags
    flipbooks = []
    if frame_tags:
        frame_list = list(frames.keys())
        for tag in frame_tags:
            fb_frames = []
            for i in range(tag["from"], tag["to"] + 1):
                if i < len(frame_list):
                    f = list(frames.values())[i]
                    fb_frames.append({
                        "sprite": f"{asset_name}_{frame_list[i]}",
                        "durationSeconds": f["duration"] / 1000.0,
                    })
            flipbooks.append({
                "name": f"FB_{asset_name}_{tag['name']}",
                "loop": True,
                "framesPerSecond": 1000.0 / list(frames.values())[0]["duration"] if frames else 8.0,
                "keyFrames": fb_frames,
            })

    return {
        "assetName": asset_name,
        "sourceTexture": texture_filename,
        "textureSize": {"width": sheet_size["w"], "height": sheet_size["h"]},
        "sprites": sprites,
        "flipbooks": flipbooks,
    }


PIVOT_PRESETS = {
    "bottom_center": {"x": 0.5, "y": 1.0},
    "center": {"x": 0.5, "y": 0.5},
    "top_left": {"x": 0.0, "y": 0.0},
}


def apply_pivot(atlas: dict, pivot_mode: str = "bottom_center") -> dict:
    """Apply a pivot preset to all frames in an atlas JSON."""
    pivot = PIVOT_PRESETS.get(pivot_mode, PIVOT_PRESETS["bottom_center"])
    for frame_data in atlas.get("frames", {}).values():
        frame_data["pivot"] = dict(pivot)
    return atlas
