"""Safe local tools exposed to the language model."""

import json
import os
import platform
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

from computer import DesktopController
from config import LINKS_FILE, WORKSPACE_DIR, VAULT_DIR, OBSIDIAN_VAULT_DIR

_MAX_NOTE_READ_CHARS = 12_000
_MAX_SEARCH_MATCHES = 20


desktop = DesktopController()


def _workspace_path(requested_path: str) -> Path:
    """Resolve a path and prevent tools from escaping the assistant workspace."""
    workspace = WORKSPACE_DIR.resolve()
    candidate = (workspace / requested_path).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise ValueError("Paths must stay inside the F.R.I.D.A.Y. workspace.")
    return candidate


def get_system_info() -> dict[str, str]:
    """Return basic operating system details."""
    return {
        "operating_system": f"{platform.system()} {platform.release()}",
        "python_version": sys.version.split()[0],
        "architecture": platform.machine(),
    }


def list_workspace_files(directory_path: str = ".") -> dict[str, Any]:
    """List a directory inside the dedicated assistant workspace."""
    try:
        directory = _workspace_path(directory_path)
        if not directory.is_dir():
            return {"error": f"Directory does not exist: {directory_path}"}
        return {
            "path": str(directory.relative_to(WORKSPACE_DIR.resolve())) or ".",
            "items": sorted(item.name for item in directory.iterdir()),
        }
    except (OSError, ValueError) as error:
        return {"error": str(error)}


def write_workspace_file(file_path: str, content: str) -> dict[str, Any]:
    """Create or replace a UTF-8 text file inside the assistant workspace."""
    try:
        target = _workspace_path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"status": "SUCCESS", "path": str(target.relative_to(WORKSPACE_DIR.resolve()))}
    except (OSError, ValueError) as error:
        return {"error": str(error)}


def launch_application(app_name: str) -> dict[str, Any]:
    """Launch an installed Windows application using Start search."""
    return desktop.launch_application(app_name)


def close_application(app_name: str) -> dict[str, Any]:
    """Close a named running application."""
    return desktop.close_application(app_name)


def type_text(text: str) -> dict[str, Any]:
    """Type text into the active application."""
    return desktop.type_text(text)


def press_key(key: str) -> dict[str, Any]:
    """Press one keyboard key in the active application."""
    return desktop.press_key(key)


def execute_shortcut(keys: list[str]) -> dict[str, Any]:
    """Press a keyboard shortcut in the active application."""
    return desktop.hotkey(keys)


def move_mouse(x: int, y: int) -> dict[str, Any]:
    """Move the mouse pointer to screen coordinates."""
    return desktop.move_mouse(x, y)


def click(x: int, y: int, button: str = "left") -> dict[str, Any]:
    """Click a screen coordinate."""
    return desktop.click(x, y, button)


def double_click(x: int, y: int) -> dict[str, Any]:
    """Double-click a screen coordinate."""
    return desktop.double_click(x, y)


def right_click(x: int, y: int) -> dict[str, Any]:
    """Right-click a screen coordinate."""
    return desktop.right_click(x, y)


def drag(start_x: int, start_y: int, end_x: int, end_y: int) -> dict[str, Any]:
    """Drag from one screen coordinate to another."""
    return desktop.drag(start_x, start_y, end_x, end_y)


def switch_window(window_name: str) -> dict[str, Any]:
    """Bring a named application window to the foreground."""
    return desktop.switch_window(window_name)


def close_active_window() -> dict[str, Any]:
    """Close the current foreground window."""
    return desktop.close_active_window()


def minimize_all_windows() -> dict[str, Any]:
    """Minimize all visible Windows applications."""
    return desktop.minimize_all_windows()


def scroll(amount: int) -> dict[str, Any]:
    """Scroll the active window."""
    return desktop.scroll(amount)


def take_screenshot() -> dict[str, Any]:
    """Save a screenshot in the assistant workspace."""
    return desktop.screenshot()


def get_screen_size() -> dict[str, int]:
    """Return the primary screen resolution so the model can aim clicks correctly."""
    return desktop.screen_size()


def _validate_http_url(candidate: str) -> str | None:
    """Normalize to https and return a safe http(s) URL, or None if invalid."""
    from urllib.parse import urlparse

    candidate = (candidate or "").strip()
    if not candidate:
        return None
    if not urlparse(candidate).scheme:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def open_url(url: str) -> dict[str, Any]:
    """Open a website in the user's default browser."""
    candidate = _validate_http_url(url)
    if candidate is None:
        return {"error": "Only http(s) URLs are allowed."}
    webbrowser.open(candidate)
    return {"status": "SUCCESS", "message": f"Opened {candidate} in the default browser."}


def get_screen_context() -> dict[str, Any]:
    """Get the active window and visible application titles."""
    return desktop.screen_context()


def _load_links() -> dict[str, str]:
    """Load user-defined link shortcuts from the project links file."""
    try:
        data = json.loads(LINKS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(name).lower(): str(url) for name, url in data.items()}


def open_custom_link(name: str) -> dict[str, Any]:
    """Open one of the user's saved link shortcuts by name."""
    links = _load_links()
    key = (name or "").strip().lower()
    if not key:
        return {"error": "Specify the link name to open."}
    if key not in links:
        known = ", ".join(sorted(links)) or "none saved yet"
        return {"error": f"No link named '{key}'. Saved links: {known}."}
    url = _validate_http_url(links[key])
    if url is None:
        return {"error": f"The saved link '{key}' has an invalid URL."}
    webbrowser.open(url)
    return {"status": "SUCCESS", "message": f"Opened link '{key}': {url}"}


def list_custom_links() -> dict[str, Any]:
    """List the user's saved link shortcuts."""
    links = _load_links()
    return {"status": "SUCCESS", "links": links or {}, "message": f"{len(links)} link(s) saved."}


def save_custom_link(name: str, url: str) -> dict[str, Any]:
    """Add or update a user-defined link shortcut after validating the URL."""
    key = (name or "").strip().lower()
    if not key or len(key) > 40 or not all(ch.isalnum() or ch in "-_ " for ch in key):
        return {"error": "Link name must be 1-40 characters: letters, numbers, spaces, or dashes."}
    safe_url = _validate_http_url(url)
    if safe_url is None:
        return {"error": "Only http(s) URLs can be saved."}
    links = _load_links()
    links[key] = safe_url
    try:
        LINKS_FILE.write_text(json.dumps(links, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as error:
        return {"error": f"Could not save links: {error}"}
    return {"status": "SUCCESS", "message": f"Saved link '{key}' -> {safe_url}"}


def play_on_spotify(query: str) -> dict[str, Any]:
    """Search for the query on Spotify Web Player in the default browser."""
    from urllib.parse import quote_plus

    query = (query or "").strip()
    if not query:
        return {"error": "Specify something to play, e.g. 'Daft Punk' or a song name."}
    webbrowser.open(f"https://open.spotify.com/search/{quote_plus(query)}")
    return {"status": "SUCCESS", "message": f"Opened Spotify search for '{query}'. Press play in the browser."}


def play_on_youtube(query: str) -> dict[str, Any]:
    """Search for the query on YouTube in the default browser."""
    from urllib.parse import quote_plus

    query = (query or "").strip()
    if not query:
        return {"error": "Specify something to play, e.g. a song, artist, or video title."}
    webbrowser.open(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
    return {"status": "SUCCESS", "message": f"Opened YouTube search for '{query}'."}


def set_volume(level: int) -> dict[str, Any]:
    """Set the master volume to an absolute level from 0 to 100."""
    return desktop.set_volume(level)


def adjust_volume(delta: int) -> dict[str, Any]:
    """Raise or lower the master volume by a percentage."""
    return desktop.adjust_volume(delta)


def toggle_mute(mute: bool | None = None) -> dict[str, Any]:
    """Mute, unmute, or toggle the master mute state."""
    return desktop.toggle_mute(mute)


def press_media_key(key: str) -> dict[str, Any]:
    """Press a media key such as play_pause, next_track, or volume_up."""
    return desktop.press_media_key(key)


def lock_workstation() -> dict[str, Any]:
    """Lock the Windows session; reversible at the login screen."""
    return desktop.lock_workstation()


def shutdown_computer(action: str, delay_seconds: int = 5) -> dict[str, Any]:
    """Schedule or cancel shutdown/restart/logoff; cancel cancels a pending shutdown."""
    return desktop.shutdown_computer(action, delay_seconds)


def create_desktop_folder(folder_name: str) -> dict[str, Any]:
    """Create a Desktop folder."""
    return desktop.create_desktop_folder(folder_name)


def create_desktop_file(filename: str, content: str = "") -> dict[str, Any]:
    """Create a UTF-8 text file on the Desktop."""
    return desktop.create_desktop_file(filename, content)


def delete_desktop_item(item_name: str) -> dict[str, Any]:
    """Permanently delete one directly named Desktop file or folder."""
    return desktop.delete_desktop_item(item_name)


# -----------------------------------------------------------------
# Vault tools (V14): direct markdown memory management. All paths are
# validated to stay inside the vault; _vault_root() falls back between
# the configured Obsidian vault and the project-local vault.
# -----------------------------------------------------------------

def _vault_root() -> Path:
    """Prefer the writable configured Obsidian vault; fall back to local."""
    try:
        if OBSIDIAN_VAULT_DIR.exists() and os.access(OBSIDIAN_VAULT_DIR, os.W_OK):
            return OBSIDIAN_VAULT_DIR
    except OSError:
        pass
    try:
        VAULT_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return VAULT_DIR


def _vault_note_path(requested_path: str) -> Path:
    """Resolve a vault-relative note path, refusing escapes and bad names."""
    requested_path = (requested_path or "").strip().replace("\\", "/")
    if not requested_path:
        raise ValueError("Specify a note path, e.g. 'notes/idea.md' or 'Idea'.")
    if not requested_path.endswith(".md"):
        requested_path += ".md"
    if any(char in requested_path for char in ":*?\"<>|"):
        raise ValueError("Note paths cannot contain : * ? \" < > | characters.")
    vault = _vault_root().resolve()
    candidate = (vault / requested_path).resolve()
    if candidate != vault and vault not in candidate.parents:
        raise ValueError("Note paths must stay inside the memory vault.")
    return candidate


def list_vault_notes() -> dict[str, Any]:
    """List all markdown notes in the memory vault with size and mtime."""
    vault = _vault_root()
    try:
        notes = sorted(vault.rglob("*.md"))
    except OSError as error:
        return {"error": f"Could not read the vault: {error}"}
    items = []
    for note in notes:
        try:
            stat = note.stat()
            items.append(
                {
                    "path": note.relative_to(vault).as_posix(),
                    "chars": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                }
            )
        except OSError:
            continue
    return {"vault": str(vault), "count": len(items), "notes": items}


def read_vault_note(note_path: str) -> dict[str, Any]:
    """Read one vault note; large notes are truncated with a flag."""
    try:
        target = _vault_note_path(note_path)
    except ValueError as error:
        return {"error": str(error)}
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"error": f"Note not found: {note_path}"}
    except OSError as error:
        return {"error": f"Could not read note: {error}"}
    truncated = len(text) > _MAX_NOTE_READ_CHARS
    return {
        "path": target.name,
        "content": text[:_MAX_NOTE_READ_CHARS],
        "chars": len(text),
        "truncated": truncated,
    }


def write_vault_note(note_path: str, content: str) -> dict[str, Any]:
    """Create or replace one vault note; parent folders auto-created."""
    try:
        target = _vault_note_path(note_path)
    except ValueError as error:
        return {"error": str(error)}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as error:
        return {"error": f"Could not write note: {error}"}
    return {
        "status": "SUCCESS",
        "path": target.name,
        "chars": len(content),
        "message": f"Wrote {len(content)} chars to {target.name}.",
    }


def append_vault_note(note_path: str, entry: str) -> dict[str, Any]:
    """Append one bullet entry to a note, creating it with a header if missing."""
    entry = (entry or "").strip()
    if not entry:
        return {"error": "Nothing to append."}
    try:
        target = _vault_note_path(note_path)
    except ValueError as error:
        return {"error": str(error)}
    bullet = entry if entry.startswith("-") else f"- {entry}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            title = target.stem.replace("_", " ").title()
            target.write_text(f"# {title}\n", encoding="utf-8")
        with target.open("a", encoding="utf-8") as file:
            file.write(f"\n{bullet}\n")
    except OSError as error:
        return {"error": f"Could not append to note: {error}"}
    return {"status": "SUCCESS", "path": target.name, "message": f"Appended to {target.name}."}


def search_vault(query: str) -> dict[str, Any]:
    """Full-text search across vault filenames and note content."""
    query = (query or "").strip()
    if not query:
        return {"error": "Specify a search query."}
    needle = query.lower()
    vault = _vault_root()
    matches = []
    try:
        for note in vault.rglob("*.md"):
            try:
                text = note.read_text(encoding="utf-8")
            except OSError:
                continue
            if needle in note.name.lower():
                matches.append({"note": note.relative_to(vault).as_posix(), "match": "filename"})
                if len(matches) >= _MAX_SEARCH_MATCHES:
                    break
            for line_number, line in enumerate(text.splitlines(), start=1):
                if needle in line.lower():
                    matches.append(
                        {
                            "note": note.relative_to(vault).as_posix(),
                            "line": line_number,
                            "context": line.strip()[:160],
                        }
                    )
                    if len(matches) >= _MAX_SEARCH_MATCHES:
                        break
            if len(matches) >= _MAX_SEARCH_MATCHES:
                break
    except OSError as error:
        return {"error": f"Could not search the vault: {error}"}
    return {"query": query, "matches": matches, "count": len(matches)}


def available_tools() -> dict[str, Any]:
    """Return the function map used when fulfilling model tool calls."""
    return {
        "get_system_info": get_system_info,
        "list_workspace_files": list_workspace_files,
        "write_workspace_file": write_workspace_file,
        "launch_application": launch_application,
        "close_application": close_application,
        "type_text": type_text,
        "press_key": press_key,
        "execute_shortcut": execute_shortcut,
        "move_mouse": move_mouse,
        "click": click,
        "double_click": double_click,
        "right_click": right_click,
        "drag": drag,
        "switch_window": switch_window,
        "close_active_window": close_active_window,
        "minimize_all_windows": minimize_all_windows,
        "scroll": scroll,
        "take_screenshot": take_screenshot,
        "get_screen_size": get_screen_size,
        "get_screen_context": get_screen_context,
        "open_url": open_url,
        "open_custom_link": open_custom_link,
        "list_custom_links": list_custom_links,
        "save_custom_link": save_custom_link,
        "play_on_spotify": play_on_spotify,
        "play_on_youtube": play_on_youtube,
        "set_volume": set_volume,
        "adjust_volume": adjust_volume,
        "toggle_mute": toggle_mute,
        "press_media_key": press_media_key,
        "lock_workstation": lock_workstation,
        "shutdown_computer": shutdown_computer,
        "create_desktop_folder": create_desktop_folder,
        "create_desktop_file": create_desktop_file,
        "delete_desktop_item": delete_desktop_item,
        "list_vault_notes": list_vault_notes,
        "read_vault_note": read_vault_note,
        "write_vault_note": write_vault_note,
        "append_vault_note": append_vault_note,
        "search_vault": search_vault,
    }


def tool_declarations() -> list[Any]:
    """Build Gemini declarations lazily so local tests need no SDK import."""
    from google.genai import types

    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="get_system_info",
                    description="Get basic operating system and Python details.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                ),
                types.FunctionDeclaration(
                    name="launch_application",
                    description="Launch an installed Windows application, such as Figma, Chrome, or Notepad.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"app_name": types.Schema(type=types.Type.STRING)}, required=["app_name"]),
                ),
                types.FunctionDeclaration(
                    name="close_application",
                    description="Close a named running Windows application.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"app_name": types.Schema(type=types.Type.STRING)}, required=["app_name"]),
                ),
                types.FunctionDeclaration(
                    name="type_text",
                    description="Type user-requested text in the currently active application.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"text": types.Schema(type=types.Type.STRING)}, required=["text"]),
                ),
                types.FunctionDeclaration(
                    name="press_key",
                    description="Press one keyboard key in the active application.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"key": types.Schema(type=types.Type.STRING)}, required=["key"]),
                ),
                types.FunctionDeclaration(
                    name="execute_shortcut",
                    description="Press a user-requested keyboard shortcut, such as ctrl+s or alt+tab.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"keys": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING))}, required=["keys"]),
                ),
                types.FunctionDeclaration(
                    name="move_mouse",
                    description="Move the pointer to a screen coordinate.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"x": types.Schema(type=types.Type.INTEGER), "y": types.Schema(type=types.Type.INTEGER)}, required=["x", "y"]),
                ),
                types.FunctionDeclaration(
                    name="click",
                    description="Click a screen coordinate.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"x": types.Schema(type=types.Type.INTEGER), "y": types.Schema(type=types.Type.INTEGER), "button": types.Schema(type=types.Type.STRING)}, required=["x", "y"]),
                ),
                types.FunctionDeclaration(
                    name="double_click",
                    description="Double-click a screen coordinate.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"x": types.Schema(type=types.Type.INTEGER), "y": types.Schema(type=types.Type.INTEGER)}, required=["x", "y"]),
                ),
                types.FunctionDeclaration(
                    name="right_click",
                    description="Right-click a screen coordinate.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"x": types.Schema(type=types.Type.INTEGER), "y": types.Schema(type=types.Type.INTEGER)}, required=["x", "y"]),
                ),
                types.FunctionDeclaration(
                    name="drag",
                    description="Drag from one screen coordinate to another.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"start_x": types.Schema(type=types.Type.INTEGER), "start_y": types.Schema(type=types.Type.INTEGER), "end_x": types.Schema(type=types.Type.INTEGER), "end_y": types.Schema(type=types.Type.INTEGER)}, required=["start_x", "start_y", "end_x", "end_y"]),
                ),
                types.FunctionDeclaration(
                    name="switch_window",
                    description="Bring a named application window to the foreground.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"window_name": types.Schema(type=types.Type.STRING)}, required=["window_name"]),
                ),
                types.FunctionDeclaration(
                    name="close_active_window",
                    description="Close the current foreground window when the user asks.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                ),
                types.FunctionDeclaration(
                    name="minimize_all_windows",
                    description="Minimize all open Windows applications when the user asks.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                ),
                types.FunctionDeclaration(
                    name="scroll",
                    description="Scroll the active window; positive is up and negative is down.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"amount": types.Schema(type=types.Type.INTEGER)}, required=["amount"]),
                ),
                types.FunctionDeclaration(
                    name="take_screenshot",
                    description="Capture the current screen into the assistant workspace.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                ),
                types.FunctionDeclaration(
                    name="get_screen_size",
                    description="Get the screen width and height in pixels so clicks land inside the display.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                ),
                types.FunctionDeclaration(
                    name="open_url",
                    description="Open a website URL in the user's default browser.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"url": types.Schema(type=types.Type.STRING)}, required=["url"]),
                ),
                types.FunctionDeclaration(
                    name="get_screen_context",
                    description="Read the active window title and visible Windows application titles.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                ),
                types.FunctionDeclaration(
                    name="create_desktop_folder",
                    description="Create a directly named folder on the Windows Desktop.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"folder_name": types.Schema(type=types.Type.STRING)}, required=["folder_name"]),
                ),
                types.FunctionDeclaration(
                    name="create_desktop_file",
                    description="Create a text file on the Windows Desktop.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"filename": types.Schema(type=types.Type.STRING), "content": types.Schema(type=types.Type.STRING)}, required=["filename"]),
                ),
                types.FunctionDeclaration(
                    name="delete_desktop_item",
                    description="Permanently delete one directly named Desktop file or folder. Only use after user confirmation.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"item_name": types.Schema(type=types.Type.STRING)}, required=["item_name"]),
                ),
                types.FunctionDeclaration(
                    name="list_workspace_files",
                    description="List files in F.R.I.D.A.Y.'s dedicated workspace.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"directory_path": types.Schema(type=types.Type.STRING)},
                    ),
                ),
                types.FunctionDeclaration(
                    name="write_workspace_file",
                    description="Write a text file inside F.R.I.D.A.Y.'s dedicated workspace.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "file_path": types.Schema(type=types.Type.STRING),
                            "content": types.Schema(type=types.Type.STRING),
                        },
                        required=["file_path", "content"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="open_custom_link",
                    description="Open one of the user's saved link shortcuts by name.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"name": types.Schema(type=types.Type.STRING)}, required=["name"]),
                ),
                types.FunctionDeclaration(
                    name="list_custom_links",
                    description="List the user's saved link shortcuts.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                ),
                types.FunctionDeclaration(
                    name="save_custom_link",
                    description="Save a named website shortcut, e.g. name 'docs' for https://docs.google.com.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"name": types.Schema(type=types.Type.STRING), "url": types.Schema(type=types.Type.STRING)},
                        required=["name", "url"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="play_on_spotify",
                    description="Search for a song, artist, or playlist on Spotify Web Player in the browser.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"query": types.Schema(type=types.Type.STRING)}, required=["query"]),
                ),
                types.FunctionDeclaration(
                    name="play_on_youtube",
                    description="Search for a video or song on YouTube in the browser.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"query": types.Schema(type=types.Type.STRING)}, required=["query"]),
                ),
                types.FunctionDeclaration(
                    name="set_volume",
                    description="Set the master volume to an absolute level from 0 to 100.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"level": types.Schema(type=types.Type.INTEGER)}, required=["level"]),
                ),
                types.FunctionDeclaration(
                    name="adjust_volume",
                    description="Raise or lower the master volume by a percentage, e.g. 10 or -15.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"delta": types.Schema(type=types.Type.INTEGER)}, required=["delta"]),
                ),
                types.FunctionDeclaration(
                    name="toggle_mute",
                    description="Mute, unmute, or toggle the master mute state.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"mute": types.Schema(type=types.Type.BOOLEAN)}),
                ),
                types.FunctionDeclaration(
                    name="press_media_key",
                    description="Press a media key: play_pause, next_track, previous_track, stop, volume_up, volume_down, or mute.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={"key": types.Schema(type=types.Type.STRING)}, required=["key"]),
                ),
                types.FunctionDeclaration(
                    name="lock_workstation",
                    description="Lock the Windows session immediately; reversible at the login screen.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                ),
                types.FunctionDeclaration(
                    name="shutdown_computer",
                    description="Schedule shutdown, restart, or logoff with a delay, or cancel a pending shutdown. Only use after explicit user confirmation.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "action": types.Schema(type=types.Type.STRING),
                            "delay_seconds": types.Schema(type=types.Type.INTEGER),
                        },
                        required=["action"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="list_vault_notes",
                    description="List all markdown notes in the memory vault with sizes and modification times.",
                    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                ),
                types.FunctionDeclaration(
                    name="read_vault_note",
                    description="Read the content of one vault note by path or name (e.g. 'User_Profile' or 'notes/idea.md').",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"note_path": types.Schema(type=types.Type.STRING)},
                        required=["note_path"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="write_vault_note",
                    description="Create or replace one markdown note in the memory vault.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "note_path": types.Schema(type=types.Type.STRING),
                            "content": types.Schema(type=types.Type.STRING),
                        },
                        required=["note_path", "content"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="append_vault_note",
                    description="Append one bullet entry to an existing vault note, creating it if missing.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "note_path": types.Schema(type=types.Type.STRING),
                            "entry": types.Schema(type=types.Type.STRING),
                        },
                        required=["note_path", "entry"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="search_vault",
                    description="Full-text search across all vault notes; matches filenames and content with line context.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"query": types.Schema(type=types.Type.STRING)},
                        required=["query"],
                    ),
                ),
            ]
        )
    ]
