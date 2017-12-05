"""This module implements aligning the score elements
to performance elements (specifically, coordinates in the MIDI
matrix).

The inputs you need for this processing are:

* MuNG file with Ly links,
* Normalized LilyPond file where the links lead,
* MIDI matrix of a performance.

On the top level, the alignment is called with a Score and a Performance.

Algorithm
---------

(...)

"""
from __future__ import print_function

import collections
import copy
import logging
import pprint
import string

import abjad
import numpy
from mhr.muscimarker_io import cropobjects_merge_bbox
from muscima.io import parse_cropobject_list

from sheet_manager.data_model.util import SheetManagerDBError

__version__ = "0.0.1"
__author__ = "Jan Hajic jr."


class SheetManagerLyParsingError(Exception):
    pass


def mung_midi_from_ly_links(cropobjects):
    """Adds the ``midi_pitch_code``data attribute for all CropObjects
    that have a ``ly_link`` data attribute.

    May return the CropObjects in a different order.
    """
    parser = LilyPondLinkPitchParser()
    _cdict = {c.objid: c for c in cropobjects}
    midi_pitch_codes = parser.process_mungos(cropobjects)
    for objid in midi_pitch_codes:
        _cdict[objid].data['midi_pitch_code'] = midi_pitch_codes[objid]

    return _cdict.values()


class LilyPondLinkPitchParser(object):
    """This is a helper class that allows interpreting backlinks
    to LilyPond files."""
    RELEVANT_CHARS = []

    # NONRELEVANT_CHARS = list("{}()[]~\\/=|<>.^!?0123456789#\"")
    NONRELEVANT_CHARS = list("{}()[]\\/=|<>.^!?#\"%-")

    TIE_CHAR = '~'

    def __init__(self):

        self.ly_data_dict = dict()
        self.ly_token_dict = dict()

    def process_mungos(self, mungos):
        """Processes a list of MuNG objects. Returns a dict: for each ``objid``
        the ``midi_pitch_code`` integer value.

        For each MuNG object that is tied, adds the ``tied=True`` attribute
        to its ``data``.
        """
        output = dict()
        _n_ties = 0
        for c in mungos:
            if 'ly_link' not in c.data:
                continue
            fname, row, col, _ = self.parse_ly_file_link(c.data['ly_link'])
            if fname not in self.ly_data_dict:
                lines, tokens = self.load_ly_file(fname, with_tokens=True)
                self.ly_data_dict[fname] = lines
                self.ly_token_dict[fname] = tokens

            if self.check_tie_before_location(row, col, ly_data=self.ly_data_dict[fname]):
                print('PROCESS FOUND TIE: mungo objid = {0},'
                      ' location = {1}'.format(c.objid, (c.top, c.left)))
                _n_ties += 1
                c.data['tied'] = True
            else:
                c.data['tied'] = False

            token = self.ly_token_from_location(row, col,
                                                ly_data=self.ly_data_dict[fname])
            midi_pitch_code = self.ly_token_to_midi_pitch(token)
            output[c.objid] = midi_pitch_code

        print('TOTAL TIED NOTES: {0}'.format(_n_ties))

        self.ly_data_dict = dict()
        return output

    @staticmethod
    def load_ly_file(path, with_tokens=False):
        """Loads the LilyPond file into a lines list, so that
        it can be indexed as ``ly_data[line][column]``"""
        with open(path) as hdl:
            lines = [LilyPondLinkPitchParser.clean_line(l)
                     for l in hdl]
        if with_tokens:
            tokens = [l.split() for l in lines]
            return lines, tokens
        return lines

    @staticmethod
    def clean_line(ly_line):
        """Clears out all the various characters we don't need
        by setting them to whitespace. Cheap and potentially very
        efficient method of cleaning the Ly file up to focus on
        pitches only.

        At the same time, the positions of retained chars must
        remain the same.
        """
        output = ly_line
        for ch in LilyPondLinkPitchParser.NONRELEVANT_CHARS:
            output = output.replace(ch, ' ')
        return output

    @staticmethod
    def check_tie_before_location(line, col, ly_data):
        """Checks whether there is a tie (``~``) in the preceding
        token. Assumes ``col`` points at the beginning of a token."""
        l = ly_data[line]
        _debugprint = 'Looking for tie: line={0}, col={1}\n\tdata: {2}' \
                      ''.format(line, col, l)

        # if l[col-1] not in string.whitespace:
        if col == 0:
            process_prev_line = True
        else:
            ll = l[:col]
            ll_tokens = ll.strip().split()

            _debugprint = 'Looking for tie: line={0}, col={1}\n\tdata: {2}' \
                          '\tll_tokens: {3}'.format(line, col, l, ll_tokens)

            if LilyPondLinkPitchParser.TIE_CHAR in ll:
                logging.debug('--------------------------------')
                logging.debug('There is a tie towards the left!')
                logging.debug(_debugprint)

            if len(ll_tokens) == 0:
                process_prev_line = True
                # logging.debug(_debugprint)
                # logging.debug('Looking at prev. line')
            elif LilyPondLinkPitchParser.TIE_CHAR in ll_tokens[-1]:
                logging.debug('--------------------------------')
                logging.debug(_debugprint)
                logging.debug('Found tie in ll_token!')
                return True
            else:
                return False

        if process_prev_line:
            logging.debug('========================')
            logging.debug('Line {0}: Processing prev. lines'.format(line))
            line -= 1
            col = LilyPondLinkPitchParser._find_location_of_last_note(line, ly_data)
            while not col:
                logging.debug('___________')
                logging.debug('Line {0}: no notes: data {1}'.format(line, ly_data[line]))
                if line == 0:
                    return False
                line -= 1
                col = LilyPondLinkPitchParser._find_location_of_last_note(line, ly_data)

            logging.debug('-------------------------')
            logging.debug(_debugprint)
            logging.debug('Got prev. line {0}, col {1}, data: {2}'.format(line, col, ly_data[line]))

            if LilyPondLinkPitchParser.TIE_CHAR in ly_data[line]:
                logging.debug('previous line {0} has tie char!'.format(line))
                logging.debug('\t\tcol: {0}, tie char position: {1}'
                      ''.format(col, ly_data[line].index(LilyPondLinkPitchParser.TIE_CHAR)))

            if LilyPondLinkPitchParser.TIE_CHAR in ly_data[line][col:]:
                logging.debug(_debugprint)
                logging.debug('Looking at prev. line, found tie! Data: {0}'.format(ly_data[line][col:]))
                return True
            else:
                return False

    @staticmethod
    def ly_line_has_notes(line):
        """Checks whether the given line contains something that can be parsed
        as a note."""
        tokens = line.split()
        has_notes = False
        for t in reversed(tokens):
            try:
                LilyPondLinkPitchParser.ly_token_to_midi_pitch(t)
            except SheetManagerLyParsingError:
                continue
            has_notes = True
            break
        return has_notes

    @staticmethod
    def _find_location_of_last_note(line, ly_data):
        """Tries to find the column at which the rightmost token
        parseable as a note on the given ``line`` of ``ly_data``
        starts. If no such token is found, returns None.
        """
        l = ly_data[line]

        _forward_whitespace_position = len(l)
        _in_token = False
        for i in reversed(range(len(l))):
            if l[i] in string.whitespace:
                if not _in_token:
                    _forward_whitespace_position = i
                    continue

                # Try token
                t = l[i+1:_forward_whitespace_position]
                _in_token = False
                if LilyPondLinkPitchParser.ly_token_is_note(t):
                    return i + 1

            elif not _in_token:
                _in_token = True

        return None

    @staticmethod
    def ly_token_from_location(line, col, ly_data):
        """Returns the token starting at the given column on the given line
        of the ``ly_data`` lines."""
        l = ly_data[line]
        lr = l[col:]
        lr_tokens = lr.split(' ')
        tr = lr_tokens[0]

        ll = l[:col]
        ll_tokens = ll.split(' ')
        tl = ll_tokens[-1]

        t = tl + tr
        t = t.strip()
        return t

    @staticmethod
    def ly_token_is_note(ly_token):
        """Checks whether the given token can be parsed as a LilyPond note."""
        try:
            LilyPondLinkPitchParser.ly_token_to_midi_pitch(ly_token)
            return True
        except SheetManagerLyParsingError:
            logging.debug('----- token {0} is not a note!'.format(ly_token))
            return False

    @staticmethod
    def ly_token_to_midi_pitch(ly_token):
        """Converts the LilyPond token into the corresponding MIDI pitch
        code. Assumes the token encodes pitch absolutely."""
        try:
            note = abjad.Note(ly_token)
            wp = note.written_pitch
            midi_code = wp.number + 60
            return midi_code
        except Exception as e:
            raise SheetManagerLyParsingError(e.message)

    @staticmethod
    def parse_ly_file_link(link_str):
        """Parses the PDF link to the original file for a note event. This
        relies on the PDF being generated from LilyPond, with the point-and-click
        functionality enabled.

        :returns: ``(path, line, normcol, something)`` -- I don't know what the
            ``something`` part of the link is... The ``path`` is a string,
            others are ints.
        """
        protocol, path, line, normcol, something = link_str.strip().split(':')
        if path.startswith('///'):
            path = path[2:]
        line = int(line) - 1
        normcol =int(normcol)
        something = int(something)

        return path, line, normcol, something


def align_score_to_performance(score, performance):
    """For each MuNG note in the score, finds the MIDI matrix cell that
    corresponds to the onset of that note.

    :param score: A ``Score`` instance. The ``mung`` view is expected.

    :param performance: A ``Performance`` instance. The MIDI matrix feature
        must be available.

    :returns: A per-page dict of lists of ``(objid, [frame, pitch])`` tuples,
        where the ``objid`` points to the corresponding MuNG object, and
        ``[frame, pitch]`` is the frame and pitch index of the MIDI matrix
        cell that corresponds to the onset of the note encoded by this
        object.

        Note that (a) not all MIDI matrix onsets have a corresponding visual
        object, (b) not all noteheads have a corresponding onset (ties!).
    """
    score.update()
    if 'mung' not in score.views:
        raise SheetManagerDBError('Score {0}: mung view not available!'
                                  ''.format(score.name))
    mung_files = score.view_files('mung')
    mungos_per_page = []
    for f in mung_files:
        mungos = parse_cropobject_list(f)
        mungos_with_pitch = [c for c in mungos
                                  if 'midi_pitch_code' in c.data]
        mungos_per_page.append(mungos_with_pitch)

    midi_matrix = performance.load_midi_matrix()

    # Algorithm:
    #  - Create hard ordering constraints:
    #     - pages (already done: mungos_per_page)
    #     - systems
    #     - left-to-right within systems
    #     - simultaneity unrolling
    #  - Unroll MIDI matrix (unambiguous)
    #  - Align with In/Del

    raise NotImplementedError()


def group_mungos_by_system(page_mungos, score_img, MIN_PEAK_WIDTH=5):
    """Groups the MuNG objects on a page into systems. Assumes
    piano music: there is a system break whenever a pitch that
    overlaps horizontally and is lower on the page is higher
    than the previous pitch.

    Only takes into account MuNG objects with
    the ``midi_pitch_code`` in their ``data`` dict.

    This method assumes no systems have been detected.

    :returns: ``(system_bboxes, system_mungos)`` where ``system_bboxes``
        are ``(top, left, bottom, right)`` tuples denoting the suggested
        system bounding boxes, and ``system_mungos`` is a list of MuNG
        objects
    """
    if len(page_mungos) < 2:
        logging.warning('Grouping MuNG objects by system'
                        ' called with only {0} objects!'
                        ''.format(len(page_mungos)))
        return [page_mungos]

    page_mungos = [m for m in page_mungos
                   if 'midi_pitch_code' in m.data]

    mungo_dict = {m.objid: m for m in page_mungos}

    sorted_mungo_columns = group_mungos_by_column(mungo_dict, page_mungos)

    logging.debug('Total MuNG object columns: {0}'
                  ''.format(len(sorted_mungo_columns)))
    logging.debug('MuNG column lengths: {0}'
                  ''.format(numpy.asarray([len(col)
                                           for col in sorted_mungo_columns.values()])))

    dividers = find_column_divider_regions(sorted_mungo_columns)

    logging.debug('Dividers: {0}'.format(dividers))

    # Now, we take the horizontal projection of the divider regions
    canvas_height = max([m.bottom for m in page_mungos])
    canvas_width = max([m.right for m in page_mungos])
    canvas_size = canvas_height + 5, \
                  canvas_width + 5
    canvas = numpy.zeros(canvas_size, dtype='uint8')
    for t, l, b, r in dividers:
        canvas[t:b, l:r] += 1

    ### DEBUG
    import matplotlib
    matplotlib.use('Qt4Agg')
    import matplotlib.pyplot as plt
    plt.imshow(score_img[:canvas_height, :canvas_width], cmap='gray')
    plt.imshow(canvas[:canvas_height, :canvas_width], alpha=0.3)

    canvas_hproj = canvas.sum(axis=1)
    plt.plot(canvas_hproj, numpy.arange(canvas_hproj.shape[0]))
    plt.show()

    # Now we find local peaks (or peak areas) of the projections.
    # - what is a peak? higher than previous, higher then next
    #   unequal
    peak_starts = []
    peak_ends = []

    peak_start_candidate = 0
    ascending = False
    for i in range(1, canvas_hproj.shape[0] - 1):
        # If current is higher than previous:
        #  - previous cannot be a peak.
        if canvas_hproj[i] > canvas_hproj[i - 1]:
            peak_start_candidate = i
            ascending = True
        # If current is higher than next:
        #  - if we are in an ascending stage: ascent ends, found peak
        if canvas_hproj[i] > canvas_hproj[i + 1]:
            if not ascending:
                continue
            peak_starts.append(peak_start_candidate)
            peak_ends.append(i)
            ascending = False

    logging.debug('Peaks: {0}'.format(zip(peak_starts, peak_ends)))
    # Filter out very sharp peaks
    peak_starts, peak_ends = map(list, zip(*[(s, e) for s, e in zip(peak_starts, peak_ends)
                                   if (e - s) > MIN_PEAK_WIDTH]))

    # Use peaks as separators between system regions.
    system_regions = []
    for s, e in zip([0] + peak_ends, peak_starts + [canvas_height]):
        region = (s+1, 1, e, canvas_width)
        system_regions.append(region)

    logging.debug('System regions:\n{0}'.format([(t, b) for t, l, b, r in system_regions]))

    system_mungos = group_mungos_by_region(page_mungos, system_regions)

    # Crop system boundaries based on mungos
    # (includes filtering out systems that have no objects)
    cropped_system_boundaries = []
    cropped_system_mungos = []
    for mungos in system_mungos:
        if len(mungos) == 0:
            continue
        t, l, b, r = cropobjects_merge_bbox(mungos)
        cropped_system_boundaries.append((t, l, b, r))
        cropped_system_mungos.append(mungos)

    # Merge vertically overlapping system regions
    sorted_system_boundaries = sorted(cropped_system_boundaries, key=lambda x: x[0])
    merge_sets = []
    current_merge_set = [0]
    for i in range(len(sorted_system_boundaries[:-1])):
        t, l, b, r = sorted_system_boundaries[i]
        nt, nl, nb, nr = sorted_system_boundaries[i+1]
        if nt <= b:
            current_merge_set.append(i + 1)
        else:
            merge_sets.append(copy.deepcopy(current_merge_set))
            current_merge_set = [i+1]
    merge_sets.append(copy.deepcopy(current_merge_set))

    logging.debug('Merge sets: {0}'.format(merge_sets))

    merged_system_boundaries = []
    for ms in merge_sets:
        regions = [sorted_system_boundaries[i] for i in ms]
        if len(regions) == 1:
            logging.debug('No overlap for merge set {0}, just adding it'
                          ''.format(regions))
            merged_system_boundaries.append(regions[0])
            continue
        mt = min([r[0] for r in regions])
        ml = min([r[1] for r in regions])
        mb = max([r[2] for r in regions])
        mr = max([r[3] for r in regions])
        merged_system_boundaries.append((mt, ml, mb, mr))
        logging.debug('Merging overlapping systems: ms {0}, regions {1}, '
                      'boundary: {2}'.format(ms, regions, (mt, ml, mb, mr)))
    merged_system_mungos = group_mungos_by_region(page_mungos,
                                                  merged_system_boundaries)

    return merged_system_boundaries, merged_system_mungos


def group_mungos_by_region(page_mungos, system_regions):
    """Group MuNG objects based on which system they belong to."""
    system_mungos = [[] for _ in system_regions]
    for i, (t, l, b, r) in enumerate(system_regions):
        for m in page_mungos:
            if (t <= m.top <= b) and (l <= m.left <= r):
                system_mungos[i].append(m)

    return system_mungos


def find_column_divider_regions(sorted_mungo_columns):
    """Within each MuNG note column, use the MIDI pitch code data
    attribute to find suspected system breaks."""
    rightmost_per_column = {l: max([m.right
                                    for m in sorted_mungo_columns[l]])
                            for l in sorted_mungo_columns}
    # Now we have the MuNG objects grouped into columns.
    # Next step: find system breaks in each column.
    system_breaks_mungos_per_col = collections.defaultdict(list)
    # Collects the pairs of MuNG objects in each column between
    # which a page break is suspected.
    for l in sorted_mungo_columns:
        m_col = sorted_mungo_columns[l]
        system_breaks_mungos_per_col[l] = []
        if len(m_col) < 2:
            continue
        for m1, m2 in zip(m_col[:-1], m_col[1:]):
            logging.debug('Col {0}: comparing pitches {1}, {2}'
                          ''.format(l, m1.data['midi_pitch_code'],
                                    m2.data['midi_pitch_code']))
            # Noteheads very close togehter in a column..?
            if (m2.top - m1.top) < m1.height:
                continue
            if m1.data['midi_pitch_code'] < m2.data['midi_pitch_code']:
                system_breaks_mungos_per_col[l].append((m1, m2))
    logging.debug('System breaks: {0}'
                  ''.format(pprint.pformat(dict(system_breaks_mungos_per_col))))
    # We can now draw dividing regions where we are certain
    # a page brerak should occur.
    dividers = []
    for l in system_breaks_mungos_per_col:
        r = rightmost_per_column[l]
        for m1, m2 in system_breaks_mungos_per_col[l]:
            t = m1.bottom + 1
            b = m2.top
            dividers.append((t, l, b, r))
    return dividers


def group_mungos_by_column(mungo_dict, page_mungos):
    """Group symbols into columns."""
    mungos_by_left = collections.defaultdict(list)
    for m in page_mungos:
        mungos_by_left[m.left].append(m)
    rightmost_per_column = {l: max([m.right for m in mungos_by_left[l]])
                            for l in mungos_by_left}
    mungo_to_leftmost = {m.objid: m.left for m in page_mungos}
    # Go greedily from left, take all objects that
    # overlap horizontally by half of the given column
    # width.
    lefts_sorted = sorted(mungos_by_left.keys())
    for i, l in list(enumerate(lefts_sorted))[:-1]:
        if mungos_by_left[l] is None:
            continue
        r = rightmost_per_column[l]
        mid_point = (l + r) / 2.
        for l2 in lefts_sorted[i + 1:]:
            if l2 >= mid_point:
                break
            for m in mungos_by_left[l2]:
                mungo_to_leftmost[m.objid] = l
            mungos_by_left[l2] = None
    mungo_columns = collections.defaultdict(list)
    for objid in mungo_to_leftmost:
        l = mungo_to_leftmost[objid]
        mungo_columns[l].append(mungo_dict[objid])

    # ...sort the MuNG columns from top to bottom:
    sorted_mungo_columns = {l: sorted(mungos, key=lambda x: x.top)
                            for l, mungos in mungo_columns.items()}
    return sorted_mungo_columns


def build_system_mungos(system_boundaries, system_mungos):
    """Creates the ``staff`` MuNG objects from the given system
    boudnaries."""
    pass