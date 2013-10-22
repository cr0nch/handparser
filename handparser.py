"""Poker hand history parser module.

It only parses PokerStars and Full Tilt Poker Tournament hands, but the plan is to parse a lot.

"""


import re
from abc import ABCMeta, abstractmethod
from collections import MutableMapping, OrderedDict
from inspect import ismethod
from decimal import Decimal
from datetime import datetime
import locale
import pytz


locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')  # need for abbreviated month names

ET = pytz.timezone('US/Eastern')
UTC = pytz.UTC
CET = pytz.timezone('Europe/Budapest')


def normalize_room(room):
    val = room.lower()
    if val in {'stars', 'pokerstars', 'ps'}:
        return 'STARS'
    elif val in {'ftp', 'full tilt', 'fulltilt', 'full tilt poker', 'fulltiltpoker'}:
        return 'FTP'
    elif val in {'pkr', 'pkr poker'}:
        return 'PKR'


def normalize_game_type(game_type):
    val = game_type.lower()
    if val in {'ring', 'cash game', 'cash'}:
        return 'CASH'
    elif val in {'tournament', 'tour'}:
        return 'TOUR'


def normalize_game(game):
    val = game.lower()
    if val in {"hold'em", 'holdem'}:
        return 'HOLDEM'
    elif val in {'omaha'}:
        return 'OMAHA'


def normalize_limit(limit):
    value = limit.lower()
    if value in {'no limit', 'nl'}:
        return 'NL'
    elif value in {'pot limit', 'pl'}:
        return 'PL'
    elif value in {'fix limit', 'fl'}:
        return 'FL'


def normalize_money_type(money_type):
    value = money_type.lower()
    if value in {'real money'}:
        return 'R'
    elif value in {'play money'}:
        return 'P'
    else:
        return value.upper()


class PokerHand(MutableMapping):
    """Abstract base class for parsers.

    The attributes can be iterated
    The class can read like a dictionary.
    Every attribute default value is None.

    Public attributes:
        poker_room          -- room ID (4 byte max) ex. STARS, FTP
        ident               -- hand id
        game_type           -- TOUR for tournaments or SNG for Sit&Go-s
        tournament_ident    -- tournament id
        tournament_level
        currency            -- 3 letter iso code USD, HUF, EUR, etc.
        buyin               -- buyin without rake
        rake                -- if game_type is TOUR it's buyin rake, if CASH it's rake from pot
        game                -- game type: HOLDEM, OMAHA, STUD, RAZZ, etc.
        limit               -- NL, PL or FL
        sb                  -- amount of small blind
        bb                  -- amount of big blind
        date                -- hand date in UTC

        table_name      -- name of the table. it's 'tournament number[ ]table number'
        max_player      -- maximum players can sit on the table, 2, 4, 6, 7, 8, 9
        button_seat     -- seat of button player, starting from 1
        button          -- player name on the button
        hero            -- name of hero
        hero_seat (int) -- seat of hero, starting from 1
        players         -- OrderedDict of tuples in form (playername, starting_stack)
                           the sequence is the seating order at the table at the start of the hand
        hero_hole_cards -- tuple of two cards, ex. ('Ah', 'As')
        flop            -- tuple of flop cards, ex. ('Ah', '2s', '2h')
        turn            -- str of turn card, ex. 'Ah'
        river           -- str of river card, ex. '2d'
        board           -- tuple of board cards, ex. ('4s', 4d', '4c', '5h')
        preflop actions -- tuple of action lines in str
        flop_actions    -- tuple of flop action lines
        turn_actions
        river_actions
        total_pot       -- total pot after end of actions (rake included)
        show_down       -- There was showd_down or wasn't (bool)
        winners         -- tuple of winner names, even when there is only one winner. ex. ('W2lkm2n')
    """
    __metaclass__ = ABCMeta

    _non_hand_attributes = ('raw', 'parsed', 'header_parsed', 'date_format')

    @abstractmethod
    def __init__(self, hand_text, parse=True):
        """Save raw hand history.

        Parameters:
            hand_text   -- str of poker hand
            parse       -- if False, hand will not parsed immediately.
                           Useful if you just want to quickly check header first.
        """
        self.raw = hand_text.strip()
        self.header_parsed = False
        self.parsed = False

    def __len__(self):
        return len(self.keys())

    def __getitem__(self, key):
        if key not in self._non_hand_attributes:
            return getattr(self, key)
        else:
            raise KeyError('You can only get it via the attribute like "hand.%s"' % key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __delitem__(self, key):
        delattr(self, key)

    def __iter__(self):
        return iter(self.keys())

    def __unicode__(self):
        return "<%s: %s hand #%s>" % (self.__class__.__name__, self.poker_room, self.ident)

    def __str__(self):
        return unicode(self).encode('utf-8')

    def keys(self):
        return [attr for attr in dir(self) if not attr.startswith('_') and
                                              attr not in self._non_hand_attributes and
                                              not ismethod(getattr(self, attr))]

    @abstractmethod
    def parse_header(self):
        """Parses the first line of a hand history."""
        pass

    @abstractmethod
    def parse(self):
        """Parse the body of the hand history, but first parse header if not yet parsed."""
        if not self.header_parsed:
            self.parse_header()

    @property
    def board(self):
        board = []
        if self.flop:
            board.extend(self.flop)
            if self.turn:
                board.append(self.turn)
                if self.river:
                    board.append(self.river)
        return tuple(board) if board else None

    def _parse_date(self, date_string):
        date = datetime.strptime(date_string, self.date_format)
        self.date = self._time_zone.localize(date).astimezone(UTC)

    def _init_seats(self, player_num):
        return [('Empty Seat %s' % num, Decimal(0)) for num in range(1, player_num + 1)]


class PokerStarsHand(PokerHand):
    """Parses PokerStars Tournament hands.

    Class specific attributes:
        poker_room          -- STARS
    """

    poker_room = 'STARS'
    date_format = '%Y/%m/%d %H:%M:%S ET'
    _time_zone = ET

    _split_pattern = re.compile(r" ?\*\*\* ?\n?|\n")
    _header_pattern = re.compile(r"""
                        ^PokerStars[ ]                          # Poker Room
                        Hand[ ]\#(?P<ident>\d*):[ ]             # Hand number
                        (?P<game_type>Tournament)[ ]            # Type
                        \#(?P<tournament_ident>\d*),[ ]         # Tournament Number
                        \$(?P<buyin>\d*\.\d{2})\+               # buyin
                        \$(?P<rake>\d*\.\d{2})[ ]               # rake
                        (?P<currency>USD|EUR)[ ]                # currency
                        (?P<game>.*)[ ]                         # game
                        (?P<limit>No[ ]Limit)[ ]                # limit
                        -[ ]Level[ ](?P<tournament_level>.*)[ ] # Level
                        \((?P<sb>.*)/(?P<bb>.*)\)[ ]            # blinds
                        -[ ].*[ ]                               # localized date
                        \[(?P<date>.*)\]$                       # ET date
                        """, re.VERBOSE)
    _table_pattern = re.compile(r"^Table '(.*)' (\d)-max Seat #(\d) is the button$")
    _seat_pattern = re.compile(r"^Seat (\d): (.*) \((\d*) in chips\)$")
    _hole_cards_pattern = re.compile(r"^Dealt to (.*) \[(..) (..)\]$")
    _pot_pattern = re.compile(r"^Total pot (\d*) .*\| Rake (\d*)$")
    _winner_pattern = re.compile(r"^Seat (\d): (.*) collected \((\d*)\)$")
    _showdown_pattern = re.compile(r"^Seat (\d): (.*) showed .* and won")
    _ante_pattern = re.compile(r".*posts the ante (\d*)")
    _board_pattern = re.compile(r"(?<=[\[ ])(..)(?=[\] ])")

    def __init__(self, hand_text, parse=True):
        """Split hand history by sections and parse."""
        super(PokerStarsHand, self).__init__(hand_text, parse)
        self._splitted = self._split_pattern.split(self.raw)

        # search split locations (basically empty strings)
        # sections[0] is before HOLE CARDS
        # sections[-1] is before SUMMARY
        self._sections = [ind for ind, elem in enumerate(self._splitted) if not elem]

        if parse:
            self.parse()

    def parse_header(self):
        match = self._header_pattern.match(self._splitted[0])
        self.game_type = TYPES[match.group('game_type')]
        self.sb = Decimal(match.group('sb'))
        self.bb = Decimal(match.group('bb'))
        self.buyin = Decimal(match.group('buyin'))
        self.rake = Decimal(match.group('rake'))
        self._parse_date(match.group('date'))
        self.game = GAMES[match.group('game')]
        self.limit = LIMITS[match.group('limit')]
        self.ident = match.group('ident')
        self.tournament_ident = match.group('tournament_ident')
        self.tournament_level = match.group('tournament_level')
        self.currency = match.group('currency')

        self.header_parsed = True

    def parse(self):
        super(PokerStarsHand, self).parse()
        self._parse_table()
        self._parse_seats()
        self._parse_hole_cards()
        self._parse_preflop()
        self._parse_street('flop')
        self._parse_street('turn')
        self._parse_street('river')
        self.show_down = "SHOW DOWN" in self._splitted
        self._parse_pot()
        self._parse_board()
        self._parse_winners()

        self.parsed = True

    def _parse_table(self):
        match = self._table_pattern.match(self._splitted[1])
        self.table_name = match.group(1)
        self.max_players = int(match.group(2))
        self.button_seat = int(match.group(3))

    def _parse_seats(self):
        players = self._init_seats(self.max_players)
        for line in self._splitted[2:]:
            match = self._seat_pattern.match(line)
            if not match:
                break
            players[int(match.group(1)) - 1] = (match.group(2), int(match.group(3)))

        self.button = players[self.button_seat - 1][0]
        self.players = OrderedDict(players)

    def _parse_hole_cards(self):
        hole_cards_line = self._splitted[self._sections[0] + 2]
        match = self._hole_cards_pattern.match(hole_cards_line)
        self.hero = match.group(1)
        self.hero_seat = self.players.keys().index(self.hero) + 1
        self.hero_hole_cards = match.group(2, 3)

    def _parse_preflop(self):
        start = self._sections[0] + 3
        stop = self._sections[1]
        self.preflop_actions = tuple(self._splitted[start:stop])

    def _parse_street(self, street):
        try:
            start = self._splitted.index(street.upper()) + 2
            stop = self._splitted.index('', start)
            street_actions = self._splitted[start:stop]
            setattr(self, "%s_actions" % street.lower(), tuple(street_actions) if street_actions else None)
        except ValueError:
            setattr(self, street, None)
            setattr(self, '%s_actions' % street.lower(), None)

    def _parse_pot(self):
        potline = self._splitted[self._sections[-1] + 2]
        match = self._pot_pattern.match(potline)
        self.total_pot = int(match.group(1))

    def _parse_board(self):
        boardline = self._splitted[self._sections[-1] + 3]
        if not boardline.startswith('Board'):
            return
        cards = self._board_pattern.findall(boardline)
        self.flop = tuple(cards[:3]) if cards else None
        self.turn = cards[3] if len(cards) > 3 else None
        self.river = cards[4] if len(cards) > 4 else None

    def _parse_winners(self):
        winners = set()
        start = self._sections[-1] + 4
        for line in self._splitted[start:]:
            if not self.show_down and "collected" in line:
                match = self._winner_pattern.match(line)
                winners.add(match.group(2))
            elif self.show_down and "won" in line:
                match = self._showdown_pattern.match(line)
                winners.add(match.group(2))

        self.winners = tuple(winners)


class FullTiltHand(PokerHand):
    """Parses Full Tilt Poker hands the same way as PokerStarsHand class.

    PokerStars and Full Tilt hand histories are very similar, so parsing them is almost identical.
    There are small differences though.

    Class specific attributes:
        poker_room        -- FTP
        tournament_level  -- None
        buyin             -- None
        rake              -- None
        currency          -- None
        table_name        -- just a number, but str type

    Extra attributes:
        flop_pot          -- pot size on the flop, before actions
        flop_num_players  -- number of players seen the flop
        turn_pot          -- pot size before turn
        turn_num_players  -- number of players seen the turn
        river_pot         -- pot size before river
        river_num_players -- number of players seen the river
        tournament_name   -- ex. "$750 Guarantee", "$5 Sit & Go (Super Turbo)"

    """
    poker_room = 'FTP'
    date_format = '%H:%M:%S ET - %Y/%m/%d'
    _time_zone = ET

    _split_pattern = re.compile(r" ?\*\*\* ?\n?|\n")

    # header patterns
    _tournament_pattern = re.compile(r"""
                        ^Full[ ]Tilt[ ]Poker[ ]                 # Poker Room
                        Game[ ]\#(?P<ident>\d*):[ ]             # Hand number
                        (?P<tournament_name>.*)[ ]              # Tournament name
                        \((?P<tournament_ident>\d*)\),[ ]       # Tournament Number
                        Table[ ](?P<table_name>\d*)[ ]-[ ]      # Table name
                        """, re.VERBOSE)
    _game_pattern = re.compile(r" - (?P<limit>NL|PL|FL|No Limit|Pot Limit|Fix Limit) (?P<game>.*?) - ")
    _blind_pattern = re.compile(r" - (\d*)/(\d*) - ")
    _date_pattern = re.compile(r" \[(.*)\]$")

    _seat_pattern = re.compile(r"^Seat (\d): (.*) \(([\d,]*)\)$")
    _button_pattern = re.compile(r"^The button is in seat #(\d)$")
    _hole_cards_pattern = re.compile(r"^Dealt to (.*) \[(..) (..)\]$")
    _street_pattern = re.compile(r"\[([^\]]*)\] \(Total Pot: (\d*)\, (\d) Players")
    _pot_pattern = re.compile(r"^Total pot ([\d,]*) .*\| Rake (\d*)$")
    _winner_pattern = re.compile(r"^Seat (\d): (.*) collected \((\d*)\),")
    _showdown_pattern = re.compile(r"^Seat (\d): (.*) showed .* and won")

    def __init__(self, hand_text, parse=True):
        super(FullTiltHand, self).__init__(hand_text, parse)

        self._splitted = self._split_pattern.split(self.raw)

        # search split locations (basically empty strings)
        # sections[0] is before HOLE CARDS
        # sections[-1] is before SUMMARY
        self._sections = [ind for ind, elem in enumerate(self._splitted) if not elem]

        if parse:
            self.parse()

    def parse_header(self):
        header_line = self._splitted[0]

        match = self._tournament_pattern.match(header_line)
        self.game_type = 'TOUR'
        self.ident = match.group('ident')
        self.tournament_name = match.group('tournament_name')
        self.tournament_ident = match.group('tournament_ident')
        self.table_name = match.group('table_name')

        match = self._game_pattern.search(header_line)
        self.limit = LIMITS[match.group('limit')]   # TODO: replace instead of lookup?
        self.game = GAMES[match.group('game')]

        match = self._blind_pattern.search(header_line)
        self.sb = Decimal(match.group(1))
        self.bb = Decimal(match.group(2))

        match = self._date_pattern.search(header_line)
        self._parse_date(match.group(1))

        self.tournament_level = self.buyin = self.rake = self.currency = None

        self.header_parsed = True

    def parse(self):
        super(FullTiltHand, self).parse()

        self._parse_seats()
        self._parse_hole_cards()
        self._parse_preflop()
        self._parse_street('flop')
        self._parse_street('turn')
        self._parse_street('river')
        self.show_down = 'SHOW DOWN' in self._splitted
        self._parse_pot()
        self._parse_winners()

        self.parsed = True

    def _parse_seats(self):
        # In hh there is no indication of max_players, so init for 9.
        players = self._init_seats(9)
        for line in self._splitted[1:]:
            match = self._seat_pattern.match(line)
            if not match:
                break
            seat_number = int(match.group(1))
            player_name = match.group(2)
            stack = int(match.group(3).replace(',', ''))
            players[seat_number - 1] = (player_name, stack)
        self.max_players = seat_number
        self.players = OrderedDict(players[:self.max_players])  # cut off unneccesary seats

        # one line before the first split.
        button_line = self._splitted[self._sections[0] - 1]
        self.button_seat = int(self._button_pattern.match(button_line).group(1))
        self.button = players[self.button_seat - 1][0]

    def _parse_hole_cards(self):
        hole_cards_line = self._splitted[self._sections[0] + 2]
        match = self._hole_cards_pattern.match(hole_cards_line)
        self.hero = match.group(1)
        self.hero_seat = self.players.keys().index(self.hero) + 1
        self.hero_hole_cards = match.group(2, 3)

    def _parse_preflop(self):
        start = self._sections[0] + 3
        stop = self._sections[1]
        self.preflop_actions = tuple(self._splitted[start:stop])

    def _parse_street(self, street):
        try:
            start = self._splitted.index(street.upper()) + 1
            self._parse_boardline(start, street)
            stop = next(v for v in self._sections if v > start)
            street_actions = self._splitted[start + 1:stop]
            setattr(self, "%s_actions" % street, tuple(street_actions) if street_actions else None)
        except ValueError:
            setattr(self, street, None)
            setattr(self, '%s_actions' % street, None)
            setattr(self, '%s_pot' % street, None)
            setattr(self, '%s_num_players' % street, None)

    def _parse_boardline(self, start, street):
        """Parse pot, num players and cards."""
        # Exceptions caught in _parse_street.
        board_line = self._splitted[start]

        match = self._street_pattern.search(board_line)
        cards = match.group(1)
        cards = tuple(cards.split()) if street == 'flop' else cards
        setattr(self, street, cards)

        pot = match.group(2)
        setattr(self, "%s_pot" % street, Decimal(pot))

        num_players = int(match.group(3))
        setattr(self, "%s_num_players" % street, num_players)

    def _parse_pot(self):
        potline = self._splitted[self._sections[-1] + 2]
        match = self._pot_pattern.match(potline.replace(',', ''))
        self.total_pot = int(match.group(1))

    def _parse_winners(self):
        winners = set()
        start = self._sections[-1] + 4
        for line in self._splitted[start:]:
            if not self.show_down and "collected" in line:
                match = self._winner_pattern.match(line)
                winners.add(match.group(2))
            elif self.show_down and "won" in line:
                match = self._showdown_pattern.match(line)
                winners.add(match.group(2))

        self.winners = tuple(winners)


class PKRHand(PokerHand):
    """Parses PKR hands.

    Class specific attributes:
        poker_room        -- PKR
        table_name        -- "#table_number - name of the table"

    Extra attributes:
        last_ident        -- last hand id
        money_type        -- 'R' for real money, 'P' for play money

    """
    poker_room = 'PKR'
    date_format = '%d %b %Y %H:%M:%S'
    currency = 'USD'
    _time_zone = UTC

    _split_pattern = re.compile(r"Dealing |\nDealing Cards\n|Taking |Moving |\n")
    _blinds_pattern = re.compile(r"^Blinds are now \$([\d.]*) / \$([\d.]*)$")
    _dealt_pattern = re.compile(r"^\[(. .)\]\[(. .)\] to (.*)$")
    _seat_pattern = re.compile(r"^Seat (\d\d?): (.*) - \$([\d.]*) ?(.*)$")
    _sizes_pattern = re.compile(r"^Pot sizes: \$([\d.]*)$")
    _card_pattern = re.compile(r"\[(. .)\]")
    _rake_pattern = re.compile(r"Rake of \$([\d.]*) from pot \d$")
    _win_pattern = re.compile(r"^(.*) wins \$([\d.]*) with: ")

    def __init__(self, hand_text, parse=True):
        """Split hand history by sections and parse."""
        super(PKRHand, self).__init__(hand_text, parse)

        self._splitted = self._split_pattern.split(self.raw)

        # search split locations (basically empty strings)
        # sections[1] is after blinds, before preflop
        # section[2] is before flop
        # sections[-1] is before showdown
        self._sections = [ind for ind, elem in enumerate(self._splitted) if not elem]

        if parse:
            self.parse()

    def parse_header(self):
        self.table_name = self._splitted[0][6:]          # cut off "Table "
        self.ident = self._splitted[1][15:]              # cut off "Starting Hand #"
        self._parse_date(self._splitted[2][20:])         # cut off "Start time of hand: "
        self.last_ident = self._splitted[3][11:]         # cut off "Last Hand #"
        self.game = GAMES[self._splitted[4][11:]]        # cut off "Game Type: "
        self.limit = LIMITS[self._splitted[5][12:]]      # cut off "Limit Type: "
        self.game_type = TYPES[self._splitted[6][12:]]   # cut off "Table Type: "
        self.money_type = MONEY_TYPES[self._splitted[7][12:]]  # cut off "Money Type: "

        match = self._blinds_pattern.match(self._splitted[8])
        self.sb = Decimal(match.group(1))
        self.bb = Decimal(match.group(2))
        self.buyin = self.bb * 100

        self.button = int(self._splitted[9][18:])  # cut off "Button is at seat "

        self.tournament_ident = None
        self.tournament_name = None
        self.tournament_level = None

    def parse(self):
        super(PKRHand, self).parse()

        self._parse_seats()
        self._parse_hero()
        self._parse_preflop()
        self._parse_street('flop')
        self._parse_street('turn')
        self._parse_street('river')
        self._parse_showdown()

    def _parse_seats(self):
        # In hh there is no indication of max_players,
        # so init for 10, as there are 10 player tables on PKR.
        players = self._init_seats(10)
        for line in self._splitted[10:]:
            match = self._seat_pattern.match(line)
            if not match:
                break
            seat_number = int(match.group(1))
            player_name = match.group(2)
            stack = Decimal(match.group(3))
            players[seat_number - 1] = (player_name, stack)
        self.max_players = seat_number
        self.players = OrderedDict(players[:self.max_players])

        button_row = self._splitted[self._sections[0] + 1]

        # cut last two because there can be 10 seats also
        # in case of one digit, the first char will be a space
        # but int() can convert it without hiccups :)
        self.button_seat = int(button_row[-2:])
        self.button = players[self.button_seat - 1][0]

    def _parse_hero(self):
        dealt_row = self._splitted[self._sections[1] + 1]
        match = self._dealt_pattern.match(dealt_row)

        first = match.group(1)[0:3:2]   # split space in the middle
        second = match.group(2)[0:3:2]
        self.hero_hole_cards = (first, second)

        self.hero = match.group(3)
        self.hero_seat = self.players.keys().index(self.hero) + 1

    def _parse_preflop(self):
        start = self._sections[1] + 2
        stop = self._splitted.index('', start + 1) - 1
        self.preflop_actions = tuple(self._splitted[start:stop])

    def _parse_street(self, street):
        street_sections = {'flop': 2, 'turn': 3, 'river': 4}
        section = street_sections[street]
        try:
            start = self._sections[section] + 1

            street_line = self._splitted[start]
            cards = map(lambda x: x[0:3:2], self._card_pattern.findall(street_line))
            setattr(self, street, tuple(cards) if street == 'flop' else cards[0])

            stop = next(v for v in self._sections if v > start) - 1
            setattr(self, "%s_actions" % street, tuple(self._splitted[start + 1:stop]))

            sizes_line = self._splitted[start - 2]
            pot = Decimal(self._sizes_pattern.match(sizes_line).group(1))
            setattr(self, "%s_pot" % street, pot)
        except IndexError:
            setattr(self, street, None)
            setattr(self, "%s_actions" % street, None)
            setattr(self, "%s_pot" % street, None)

    def _parse_showdown(self):
        start = self._sections[-1] + 1

        rake_line = self._splitted[start]
        match = self._rake_pattern.match(rake_line)
        self.rake = Decimal(match.group(1))

        winners = []
        total_pot = self.rake
        for line in self._splitted[start:]:
            if 'shows' in line:
                self.show_down = True
            elif 'wins' in line:
                match = self._win_pattern.match(line)
                winners.append(match.group(1))
                total_pot += Decimal(match.group(2))

        self.winners = tuple(winners)
        self.total_pot = total_pot
