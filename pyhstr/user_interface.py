import curses
import re
import sys
from typing import Dict, List, Optional, Pattern, Union

COLORS: Dict[str, Optional[int]] = {
    # yet to be initialized
    "normal": None,
    "highlighted-white": None,
    "highlighted-green": None,
    "highlighted-red": None,
    "white": None,
    "bold-red": None,
}

PYHSTR_LABEL = (
    "Type to filter, UP/DOWN move, RET/TAB select, DEL remove, ESC quit, C-f add/rm fav"
)
PYHSTR_STATUS = "- view:{} (C-/) - regex mode:{} (C-e) - case:{} (C-t) - page {}/{} -"

PS1 = getattr(sys, "ps1", ">>> ")

DISPLAY: Dict[str, Dict[Union[int, bool], str]] = {
    "view": {
        0: "sorted",
        1: "favorites",
        2: "history",
    },
    "case": {
        True: "sensitive",
        False: "insensitive",
    },
    "regex_mode": {
        True: "on",
        False: "off",
    },
}


class UserInterface:
    def __init__(self, app):
        self.app = app
        self.page = Page(self.app)
        self.search_string = ""

    def _addstr(
        self, y_coord: int, x_coord: int, text: str, color_info: Optional[int]
    ) -> None:
        """
        Works around curses' limitation of drawing at bottom right corner
        of the screen, as seen on https://stackoverflow.com/q/36387625
        """
        screen_height: int
        screen_width: int
        screen_height, screen_width = self.app.stdscr.getmaxyx()
        if x_coord + len(text) == screen_width and y_coord == screen_height - 1:
            try:
                self.app.stdscr.addstr(y_coord, x_coord, text, color_info)
            except curses.error:
                pass
        else:
            self.app.stdscr.addstr(y_coord, x_coord, text, color_info)

    @staticmethod
    def init_color_pairs() -> None:
        mapping: Dict[int, List[int]] = {
            1: [curses.COLOR_WHITE, curses.COLOR_BLACK],
            2: [0, 15],
            3: [15, curses.COLOR_GREEN],
            4: [15, curses.COLOR_RED],
            5: [15, 0],
            6: [curses.COLOR_RED, 0, curses.A_BOLD],
        }

        for idx, color in enumerate(COLORS, 1):
            curses.init_pair(idx, mapping[idx][0], mapping[idx][1])
            if len(mapping[idx]) > 2:
                COLORS[color] = curses.color_pair(idx) | mapping[idx][2]
            else:
                COLORS[color] = curses.color_pair(idx)

    def populate_screen(self) -> None:
        self.app.stdscr.clear()
        current_page = self.app.user_interface.page.value
        total_pages = self.app.user_interface.page.total_pages()

        status = PYHSTR_STATUS.format(
            DISPLAY["view"][self.app.view],
            DISPLAY["regex_mode"][self.app.regex_mode],
            DISPLAY["case"][self.app.case_sensitivity],
            current_page if total_pages > 0 else 0,
            total_pages,
        ).ljust(curses.COLS - 1)

        entries = self.page.get_page()

        for index, entry in enumerate(entries):
            # print everything first (normal),
            # then print found matches (in red)
            # then print favorites (white)
            # then print selected on top of all that (green)
            try:
                padded_entry = entry.ljust(curses.COLS - 1)
                self._addstr(index + 3, 1, padded_entry, COLORS["normal"])
                substring_indexes = self.get_substring_indexes(entry)

                if substring_indexes:
                    for idx, letter in enumerate(entry):
                        if idx in substring_indexes:
                            self.app.stdscr.attron(COLORS["bold-red"])
                            self.app.stdscr.addch(index + 3, idx + 1, letter)
                            self.app.stdscr.attroff(COLORS["bold-red"])

                if entry in self.app.commands[1]:  # in favorites
                    self._addstr(index + 3, 1, padded_entry, COLORS["white"])

                if index == self.app.user_interface.page.selected.value:
                    self._addstr(
                        index + 3, 1, padded_entry, COLORS["highlighted-green"]
                    )
            except curses.error:
                pass

        self._addstr(1, 1, PYHSTR_LABEL, COLORS["normal"])
        self._addstr(2, 1, status, COLORS["highlighted-white"])
        self._addstr(0, 1, PS1 + self.search_string, COLORS["normal"])

    def prompt_for_deletion(self, command: str) -> None:
        prompt = f"Do you want to delete all occurences of {command}? y/n"
        self._addstr(1, 0, "".ljust(curses.COLS), COLORS["normal"])
        self._addstr(1, 1, prompt, COLORS["highlighted-red"])

    def show_regex_error(self) -> None:
        prompt = "Invalid regex. Try again."
        self._addstr(1, 0, "".ljust(curses.COLS), COLORS["normal"])
        self._addstr(1, 1, prompt, COLORS["highlighted-red"])
        self._addstr(0, 1, PS1 + self.search_string, COLORS["normal"])

    def get_substring_indexes(self, entry: str) -> List[int]:
        return [
            index
            for m in self.create_search_regex().finditer(entry)
            for index in range(m.start(), m.end())
        ]

    def create_search_regex(self) -> Pattern:
        try:
            if self.app.case_sensitivity:
                if self.app.regex_mode:
                    return re.compile(self.search_string)
                return re.compile(re.escape(self.search_string))
            else:
                if self.app.regex_mode:
                    return re.compile(self.search_string, re.IGNORECASE)
                return re.compile(re.escape(self.search_string), re.IGNORECASE)
        except re.error:
            self.show_regex_error()
            self.app.commands[self.app.view] = []
            self.populate_screen()
            return re.compile(r"this regex doesn't match anything^")  # thanks Akuli


class SelectedItem:  # pylint: disable=too-few-public-methods
    def __init__(self, app):
        self.value = 0
        self.app = app

    def move(self, direction: int) -> None:
        page_size = self.app.user_interface.page.get_page_size()
        self.value += direction

        try:
            self.value %= page_size
        except ZeroDivisionError:
            return None

        if direction == 1 and self.value == 0:
            self.app.user_interface.page.turn(1)
        elif direction == -1 and self.value == (page_size - 1):
            self.app.user_interface.page.turn(-1)
            self.value = self.app.user_interface.page.get_page_size() - 1


class Page:
    def __init__(self, app):
        self.value = 1
        self.app = app
        self.selected = SelectedItem(self.app)

    def turn(self, direction: int) -> None:
        """
        Paging starts from 1 but we want it to start at 0,
        because that's how our calculation with modulo works.

        So, if the indexing started from zero, we would have had:

        self.value = (self.value + 1) % total_pages

        ...which is increment and wrap around.

        Since we want the value to start at 1, we should:

        - subtract 1 from it when using it, because we want it to
        comply with the condition that page values start from 1,
        so we can use it in the modulo calculation (modulo needs
        zero-based indexing);

        - add 1 when setting it, because what modulo gives is
        zero-based indexing, and we want to match the pages start
        from 1 condition.

        This gives:

        self.value = ((self.value - 1 + 1) % total_pages) + 1

        ... where -1+1 happens to cancel itself.
        """
        self.value = ((self.value - 1 + direction) % self.total_pages()) + 1

    def total_pages(self) -> int:
        return len(range(0, len(self.app.commands[self.app.view]), curses.LINES - 3))

    def get_page_size(self) -> int:
        return len(self.get_page())

    def get_page(self) -> List[str]:
        return self.app.commands[self.app.view][
            (self.value - 1) * (curses.LINES - 3) : self.value * (curses.LINES - 3)
        ]

    def get_selected(self) -> str:
        return self.get_page()[self.selected.value]
