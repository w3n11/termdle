import os
import requests
from blessed import Terminal, keyboard
from time import sleep
from json import dumps, loads, JSONDecodeError
from datetime import datetime, date, timedelta
from calendar import monthrange
import subprocess
import platform
from typing import Any, Callable
from collections import Counter
import sys
from colorama import just_fix_windows_console
import tempfile


# --- PyInstaller helper function --- (start)
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS  # type: ignore
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)
# --- PyInstaller helper function --- (end)


def get_app_data_dir(app_name: str = "Termdle") -> str:
    os_name = platform.system()
    home = os.path.expanduser("~")

    if os_name == "Windows":
        # Windows: %APPDATA%\Termdle (ie. C:\Users\username\AppData\Roaming\Termdle)
        base_path = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    elif os_name == "Darwin":
        # macOS: ~/Library/Application Support/Termdle
        base_path = os.path.join(home, "Library", "Application Support")
    else:
        # Linux a ostatní: ~/.local/share/Termdle
        base_path = os.environ.get("XDG_DATA_HOME", os.path.join(home, ".local", "share"))

    app_dir = os.path.join(base_path, app_name)
    os.makedirs(app_dir, exist_ok=True)

    return app_dir


# GLOBALS
term: Terminal = Terminal()
DATA_PATH = get_app_data_dir("Termdle")
DATA_FILE = os.path.join(DATA_PATH, "data.json")


def WORDLE_GREEN(text: str) -> str:  # noqa: N802
    return term.white_bold + term.on_color_rgb(83, 141, 78) + text + term.normal


def WORDLE_YELLOW(text: str) -> str:  # noqa: N802
    return term.white_bold + term.on_color_rgb(181, 159, 59) + text + term.normal


def WORDLE_GRAY(text: str) -> str:  # noqa: N802
    return term.white_bold + term.on_color_rgb(58, 58, 60) + text + term.normal


def WORDLE_UNUSED(text: str) -> str:  # noqa: N802
    return term.white + term.on_color_rgb(18, 18, 19) + text + term.normal


def WORDLE_RED(text: str) -> str:  # noqa: N802
    return term.white_bold + term.on_color_rgb(213, 94, 98) + text + term.normal


def log_error(description: str, error: Exception) -> None:
    with open(file=os.path.join(DATA_PATH, "latest_error.txt"), mode="w", encoding="utf-8") as f:
        f.write(f"{description}\n\n{error}\n")


def copy_to_clipboard(text: str) -> bool:
    # This feature is a candidate for review,
    # as most of it was created using AI to make it work for now.
    try:
        os_name: str = platform.system()
        if os_name == "Windows":
            subprocess.run(
                "chcp 65001 > nul & clip",
                input=text,
                text=True,
                encoding="utf-8",
                shell=True,
                check=True
            )
        elif os_name == "Darwin":  # macOS
            subprocess.run("pbcopy", input=text, text=True, check=True)
        else:  # Linux
            try:  # Wayland
                subprocess.run(["wl-copy"], input=text, text=True, check=True)
            except FileNotFoundError:
                try:  # X11
                    subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)
                except FileNotFoundError:
                    subprocess.run(["xsel", "--clipboard", "--input"], input=text, text=True, check=True)
        return True
    except Exception as e:
        log_error("Copying failed", e)
        return False


def validate_hard_mode(guess: str, solution: str, guesses: list[str]) -> tuple[bool, str]:
    if not guesses:
        return True, ""

    known_greens: list[str] = [""] * 5
    min_required_counts: Counter = Counter()

    for prev_guess in guesses:
        colors: list[Callable] = evaluate_guess(prev_guess, solution)
        current_guess_counts = Counter()

        for i, (char, col) in enumerate(zip(prev_guess, colors)):
            if col == WORDLE_GREEN:
                known_greens[i] = char
                current_guess_counts[char] += 1
            elif col == WORDLE_YELLOW:
                current_guess_counts[char] += 1

        for char, count in current_guess_counts.items():
            if count > min_required_counts[char]:
                min_required_counts[char] = count

    for i, required_char in enumerate(known_greens):
        if required_char and guess[i] != required_char:
            ord_suffix = ["st", "nd", "rd", "th", "th"][i]
            return False, f"{i + 1}{ord_suffix} letter must be {required_char.upper()}"

    guess_counts: Counter = Counter(guess)
    for char, required_count in min_required_counts.items():
        if guess_counts[char] < required_count:
            if required_count == 1:
                return False, f"Guess must contain {char.upper()}"
            else:
                return False, f"Guess must contain {required_count} {char.upper()}'s"
    return True, ""


def generate_share_text(date_str: str, solution: str, guesses: list[str], hard_mode: bool) -> str:
    """Generates a standard Wordle result to share via plaintext methods."""
    start_date: date = date(2021, 6, 19)
    current_day: date = date.fromisoformat(date_str)
    wordle_number: int = (current_day - start_date).days

    base_score: str = f"{len(guesses)}/6" if solution in guesses else "X/6"
    score: str = f"{base_score}*" if hard_mode else base_score
    lines: list[str] = [f"Wordle {wordle_number} {score}\n"]

    for guess in guesses:
        colors = evaluate_guess(guess, solution)
        row_emoji = ""
        for color in colors:
            if color == WORDLE_GREEN:
                row_emoji += "🟩"
            elif color == WORDLE_YELLOW:
                row_emoji += "🟨"
            else:
                row_emoji += "⬛"
        lines.append(row_emoji)

    return "\n".join(lines)


def load_user_preferences() -> dict[str, Any]:
    """
    Loads or creates empty user preference dict in data.json.
    Used ie. for remembering user choice about solving Wordle in hard mode.
    """
    data: dict[str, dict] = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, mode="r", encoding="utf-8") as f:
                data = loads(f.read())
        except JSONDecodeError:
            pass

    data.setdefault("user_preferences", {})
    data.setdefault("wordles", {})

    safe_save_json(DATA_FILE, data)
    return data["user_preferences"]


def save_user_preferences(current_preferences: dict[str, Any], key: str | None, new_value: Any) -> None:
    if key:
        current_preferences[key] = new_value

    data: dict[str, dict] = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, mode="r", encoding="utf-8") as f:
                data = loads(f.read())
        except JSONDecodeError:
            pass

    data.setdefault("wordles", {})
    data["user_preferences"] = current_preferences

    safe_save_json(DATA_FILE, data)


def save_game(date_str: str, solution: str, guesses: list[str], is_hard_mode: bool) -> None:
    data: dict[str, dict] = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, mode="r", encoding="utf-8") as f:
                data = loads(f.read())
        except (JSONDecodeError, PermissionError):
            pass

    data.setdefault("wordles", {})
    data.setdefault("user_preferences", {})

    data["wordles"][date_str] = [solution, guesses, is_hard_mode]

    safe_save_json(DATA_FILE, data)


def safe_save_json(filepath: str, data: dict) -> None:
    dir_name = os.path.dirname(filepath)
    fd, temp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(dumps(data, indent=4))

        os.replace(temp_path, filepath)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        log_error("Atomic save failed", e)
        raise e


def load_wordle(date_str: str) -> tuple[str, list[str], bool] | None:
    data: dict[str, dict] = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, mode="r", encoding="utf-8") as f:
                data = loads(f.read())
        except JSONDecodeError:
            pass

    data.setdefault("wordles", {})
    default_hard_mode: bool = data.setdefault("user_preferences", {}).get("hard_mode", False)

    if date_str in data["wordles"]:
        saved = data["wordles"][date_str]
        solution = saved[0]
        guesses = saved[1]
        hard_mode = saved[2] if len(saved) > 2 else default_hard_mode
        return solution, guesses, hard_mode

    new_solution: str | None = download_wordle(date_str)
    if new_solution is None:
        return None

    data["wordles"][date_str] = [new_solution, [], default_hard_mode]
    with open(DATA_FILE, mode="w", encoding="utf-8") as f:
        f.write(dumps(data, indent=4))

    return new_solution, [], default_hard_mode


def download_wordle(date_str: str, max_attempts: int = 3) -> str | None:
    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        attempt: int = 0
        while attempt < max_attempts:
            try:
                print(term.clear)
                print(term.move_y(term.height // 2))  # type: ignore
                print(term.center(f"Downloading Wordle for {date_str}... (attempt {attempt + 1}/{max_attempts})"))

                response = requests.get(f"https://www.nytimes.com/svc/wordle/v2/{date_str}.json", timeout=5)
                response.raise_for_status()
                data = response.json()
                solution = data.get("solution")
                if solution:
                    return solution
                else:
                    raise KeyError("Klíč 'solution' nenalezen v JSONu.")

            except (requests.exceptions.RequestException, ValueError, KeyError) as e:
                log_error(f"Network error on attempt {attempt + 1}", e)
                attempt += 1
                sleep(2 ** attempt)
        return None


def date_picker(current_date_str: str) -> str:
    try:
        current_date: date = datetime.strptime(current_date_str, "%Y-%m-%d").date()
    except ValueError:
        current_date = date.today()

    year: int = current_date.year
    month: int = current_date.month
    day: int = current_date.day

    focused_field: int = 2

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        last_width: int = -1
        last_height: int = -1
        force_redraw: bool = True

        while term.inkey(timeout=0):  # flush queued keys
            pass

        while True:
            _, max_days = monthrange(year, month)
            if day > max_days:
                day = max_days

            today = date.today()
            first_day = date(2021, 6, 19)
            current_date = date(year, month, day)

            if current_date > today:
                year = today.year
                month = today.month
                day = today.day
            elif current_date < first_day:
                year = first_day.year
                month = first_day.month
                day = first_day.day

            current_width, current_height = term.width, term.height
            if force_redraw or current_width != last_width or current_height != last_height:
                last_width, last_height = current_width, current_height
                force_redraw = False

            print(term.clear)
            print(term.move_y(term.height // 2 - 2))  # type: ignore

            y_str = term.black_on_white(f"{year:04d}") if focused_field == 0 else f"{year:04d}"
            m_str = term.black_on_white(f"{month:02d}") if focused_field == 1 else f"{month:02d}"
            d_str = term.black_on_white(f"{day:02d}") if focused_field == 2 else f"{day:02d}"

            date_display = f"{y_str} - {m_str} - {d_str}"
            print(term.move_y(term.height // 2) + term.center(date_display))  # type: ignore
            print(term.move_y(term.height // 2 + 3) + term.center(term.dim(  # type: ignore
                "Esc = Cancel | Enter = Confirm date | Ctrl+C = Exit"
            )))

            key_pressed: keyboard.Keystroke = term.inkey(timeout=0.1)

            if not key_pressed:
                continue

            force_redraw = True  # reset

            if key_pressed.name == "KEY_ESCAPE":
                return current_date_str
            elif key_pressed.name == "KEY_ENTER":
                return f"{year:04d}-{month:02d}-{day:02d}"

            elif key_pressed.name == "KEY_LEFT":
                focused_field = (focused_field - 1) % 3
            elif key_pressed.name == "KEY_RIGHT":
                focused_field = (focused_field + 1) % 3

            elif key_pressed.name == "KEY_UP":
                if focused_field == 0:
                    year += 1
                elif focused_field == 1:
                    month = month + 1 if month < 12 else 1
                elif focused_field == 2:
                    day = day + 1 if day < max_days else 1

            elif key_pressed.name == "KEY_DOWN":
                if focused_field == 0:
                    year -= 1
                elif focused_field == 1:
                    month = month - 1 if month > 1 else 12
                elif focused_field == 2:
                    day = day - 1 if day > 1 else max_days


def load_valid_words() -> set[str]:
    try:
        with open(file=resource_path("valid_wordle_words.txt"), mode="r", encoding="utf-8") as f:
            return set(word.strip().lower() for word in f.readlines())
    except FileNotFoundError:
        return set()


def evaluate_guess(guess: str, solution: str) -> list[Callable]:
    colors: list[Callable] = [WORDLE_GRAY] * 5
    sol_letters: list[str | None] = list(solution)
    guess_letters: list[str] = list(guess)

    for i in range(5):
        if guess_letters[i] == sol_letters[i]:
            colors[i] = WORDLE_GREEN
            sol_letters[i] = None

    for i in range(5):
        if colors[i] != WORDLE_GREEN and guess_letters[i] in sol_letters:
            colors[i] = WORDLE_YELLOW
            sol_letters[sol_letters.index(guess_letters[i])] = None

    return colors


def get_keyboard_status(solution: str, guesses: list[str]) -> dict[str, str]:
    status: dict[str, str] = {chr(i): "unused" for i in range(97, 123)}

    for guess in guesses:
        colors = evaluate_guess(guess, solution)
        for i, letter in enumerate(guess):
            color = colors[i]

            if color == WORDLE_GREEN:
                status[letter] = "green"
            elif color == WORDLE_YELLOW and status[letter] != "green":
                status[letter] = "yellow"
            elif color == WORDLE_GRAY and status[letter] not in ("green", "yellow"):
                status[letter] = "gray"

    return status


def print_game_status(
        guesses: list[str],
        solution: str,
        date_str: str,
        game_hard_mode: bool,
        current_input: str,
        message: str,
        message_is_bad_news: bool) -> None:
    keyboard_layout: list[str] = ["qwertzuiop", "asdfghjkl", "yxcvbnm"]
    # Super fancy print - start
    print(term.clear)
    print(term.move_y(term.height // 2 - 12) + term.center(f"--- WORDLE: {date_str} ---"))  # type: ignore
    print(term.move_y(term.height // 2 - 11) + term.center(term.red("HARD MODE") if game_hard_mode else ""))  # type: ignore

    kbd_status = get_keyboard_status(solution, guesses)
    for i in range(6):
        y_pos = (term.height // 2 - 9) + (i * 2)

        if i < len(guesses):
            guess = guesses[i]
            colors = evaluate_guess(guess, solution)
            formatted_chars = []

            for char, col_fn in zip(guess, colors):
                formatted_chars.append(col_fn(f" {char.upper()} "))

            print(term.move_y(y_pos) + term.center(" ".join(formatted_chars)))  # type: ignore

        elif i == len(guesses) and len(guesses) < 6 and solution not in guesses:
            display_word = current_input.ljust(5, "_").upper()
            formatted_chars = []

            for char in display_word:
                if char != "_" and game_hard_mode and kbd_status.get(char.lower()) == "gray":
                    formatted_chars.append(WORDLE_RED(f" {char} "))
                else:
                    formatted_chars.append(WORDLE_GRAY(f" {char} "))

            print(term.move_y(y_pos) + term.center(" ".join(formatted_chars)))  # type: ignore

        else:
            empty_chars = [WORDLE_UNUSED("   ") for _ in range(5)]
            print(term.move_y(y_pos) + term.center(" ".join(empty_chars)))  # type: ignore

    kbd_start_y = (term.height // 2) + 4

    for row_idx, row in enumerate(keyboard_layout):
        formatted_row = []
        for char in row:
            char_status = kbd_status[char]
            btn_text = " " + char.upper() + " "

            if char_status == "green":
                formatted_row.append(WORDLE_GREEN(btn_text))
            elif char_status == "yellow":
                formatted_row.append(WORDLE_YELLOW(btn_text))
            elif char_status == "gray":
                formatted_row.append(term.color_rgb(58, 58, 60) + btn_text + term.normal)
            else:
                formatted_row.append(term.white_on_black(btn_text))

        offset = "  " * row_idx
        print(term.move_y(kbd_start_y + row_idx) + term.center(offset + " ".join(formatted_row)))  # type: ignore

    if message:
        if message_is_bad_news:
            print(term.move_y(term.height // 2 + 8) + term.center(term.red(message)))  # type: ignore
        else:
            print(term.move_y(term.height // 2 + 8) + term.center(term.dim(message)))  # type: ignore

    if solution in guesses:
        print(term.move_y(term.height // 2 + 10) + term.center(term.green(f"SUCCESS | {len(guesses)}/6")))  # type: ignore
    elif len(guesses) >= 6:
        print(term.move_y(term.height // 2 + 10) + term.center(term.red(f"FAIL | Solution: {solution.upper()}")))  # type: ignore

    game_finished: bool = solution in guesses or len(guesses) >= 6
    if game_finished:
        confirm_guess_prompt = " | Ctrl+E = Copy score"
    else:
        confirm_guess_prompt = " | Enter = Confirm your guess"
    if len(guesses) > 0:
        change_mode_prompt: str = ""
    else:
        change_mode_prompt = " | Tab = Change mode"
    print(term.move_y(term.height // 2 + 12) + term.center(term.dim(f"Esc = Choose a date{confirm_guess_prompt}{change_mode_prompt} | Ctrl+C = Exit")))  # type: ignore
    # Super fancy print - end


def play_wordle(date_str: str, solution: str, guesses: list[str], valid_words: set[str], game_hard_mode: bool) -> None | str:
    current_input: str = ""
    message: str = ""
    today: date = date.today()
    first_day: date = date(2021, 6, 19)
    current_day: date = date.fromisoformat(date_str)
    message_is_bad_news: bool = False

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        last_width: int = -1
        last_height: int = -1
        force_redraw: bool = True

        while term.inkey(timeout=0):  # flush queued keys
            pass

        while True:
            current_width, current_height = term.width, term.height
            if force_redraw or current_width != last_width or current_height != last_height:
                last_width, last_height = current_width, current_height
                force_redraw = False

                print_game_status(
                    guesses=guesses,
                    solution=solution,
                    date_str=date_str,
                    game_hard_mode=game_hard_mode,
                    current_input=current_input,
                    message=message,
                    message_is_bad_news=message_is_bad_news
                )

            key_pressed: keyboard.Keystroke = term.inkey(timeout=0.1)

            if not key_pressed:
                continue

            force_redraw = True  # reset
            message = ""  # reset
            message_is_bad_news = False  # reset

            # Key press evaluation
            if not key_pressed.is_sequence and key_pressed == "\x05":  # Ctrl+E (Export)
                share_text = generate_share_text(date_str, solution, guesses, game_hard_mode)
                if copy_to_clipboard(share_text):
                    message = "Score copied!"
                else:
                    message = "Error when copying."
                    message_is_bad_news = True
                continue

            if key_pressed.name == "KEY_TAB":
                if len(guesses) > 0:
                    message = "Mode locked after 1st guess."
                    message_is_bad_news = True
                    continue

                game_hard_mode = not game_hard_mode
                user_prefs = load_user_preferences()
                save_user_preferences(user_prefs, "hard_mode", game_hard_mode)
                save_game(date_str, solution, guesses, game_hard_mode)
                continue

            if key_pressed.name == "KEY_ESCAPE":
                return
            elif key_pressed.name == "KEY_LEFT" and current_day > first_day:
                save_game(date_str, solution, guesses, game_hard_mode)
                return "LEFT"
            elif key_pressed.name == "KEY_RIGHT" and current_day < today:
                save_game(date_str, solution, guesses, game_hard_mode)
                return "RIGHT"

            game_finished: bool = solution in guesses or len(guesses) >= 6
            if game_finished:
                continue

            if key_pressed.name in ("KEY_BACKSPACE", "KEY_DELETE"):
                current_input = current_input[:-1]
            elif key_pressed.name == "KEY_ENTER":
                if len(current_input) != 5:
                    message = "Not a valid word"
                    message_is_bad_news = True
                elif valid_words and current_input.lower() not in valid_words:
                    message = "Not a valid word"
                    message_is_bad_news = True
                else:
                    if game_hard_mode:  # hard mode eval
                        is_hm_valid, hm_error_msg = validate_hard_mode(current_input.lower(), solution, guesses)
                        if not is_hm_valid:
                            message = hm_error_msg
                            message_is_bad_news = True
                            continue

                    guesses.append(current_input.lower())
                    save_game(date_str, solution, guesses, game_hard_mode)
                    current_input = ""
            elif key_pressed.is_sequence is False and key_pressed.isalpha() and len(current_input) < 5:
                current_input += key_pressed.lower()


def main() -> None:
    current_date = date.today()
    current_date_str: str = current_date.isoformat()
    valid_words = load_valid_words()

    today = date.today()
    first_day = date(2021, 6, 19)

    while True:
        with term.fullscreen(), term.cbreak(), term.hidden_cursor():
            print(term.clear)
            print(term.move_y(term.height // 2) + term.center(f"Loading Wordle for {current_date_str}..."))  # type: ignore

        loaded: tuple[str, list[str], bool] | None = load_wordle(current_date_str)
        current_date = date.fromisoformat(current_date_str)

        if loaded is None:
            with term.fullscreen(), term.cbreak(), term.hidden_cursor():
                print(term.clear)
                print(term.move_y(term.height // 2) + term.center(term.red(f"Could not download Wordle for {current_date_str}")))  # type: ignore
                print(term.move_y(term.height // 2 + 2) + term.center("Press ESC to choose a different date."))  # type: ignore
                while True:
                    key = term.inkey()
                    if key.name == "KEY_ESCAPE":
                        break
            current_date_str = date_picker(current_date_str)
            continue

        solution, guesses, game_hard_mode = loaded
        switch_day: str | None = play_wordle(current_date_str, solution, guesses, valid_words, game_hard_mode)
        if switch_day:
            if switch_day == "LEFT" and current_date > first_day:
                current_date_str = date.isoformat(current_date - timedelta(days=1))
            elif switch_day == "RIGHT" and current_date < today:
                current_date_str = date.isoformat(current_date + timedelta(days=1))
        else:
            current_date_str = date_picker(current_date_str)


if __name__ == "__main__":
    just_fix_windows_console()
    try:
        main()
    except KeyboardInterrupt:
        print(term.clear + term.home, end="")
