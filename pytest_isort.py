# -*- coding: utf-8 -*-
import os

import isort
import py
import pytest


__version__ = '0.1.0'


MTIMES_HISTKEY = 'isort/mtimes'


def pytest_addoption(parser):
    group = parser.getgroup('general')
    group.addoption('--isort', action='store_true', help=(
        'perform import ordering checks on .py files'))

    parser.addini('isort_ignore', type='linelist', help=(
        'each line specifies a glob filename pattern which will be ignored. '
        'Example: */__init__.py'
    ))

    parser.addini('isort_extensions', type='args', default=[".py"], help=(
        'extensions of files that should be isorted. '
        'Example: .py .pyx'
    ))


def pytest_sessionstart(session):
    config = session.config
    if config.option.isort:
        config._isort_mtimes = config.cache.get(MTIMES_HISTKEY, {})
        config._isort_ignore = FileIgnorer(config.getini('isort_ignore'))
        config._isort_extensions = config.getini('isort_extensions')


def pytest_collect_file(path, parent):
    config = parent.config
    if config.option.isort and path.ext in config._isort_extensions:
        if not config._isort_ignore(path):
            return IsortItem(path, parent)


def pytest_sessionfinish(session):
    config = session.config

    # isort might not be enabled, lets check if we have a mtimes dict.
    if hasattr(config, '_isort_mtimes'):
        config.cache.set(MTIMES_HISTKEY, config._isort_mtimes)


def isort_check_file(path):
    """
    Given a file path, this function executes the actual isort check.
    """

    sorter = isort.SortImports(str(path), check=True, show_diff=True)
    return sorter.incorrectly_sorted


class FileIgnorer:
    """
    This class helps to maintain a list of ignored filepaths.
    FileIgnorer parses the "isort_ignore" list from pytest.ini and provides an
    interface to check if a certain filepath should be ignored.

    Based on the Ignorer class from pytest-pep8.
    """

    def __init__(self, ignorelines):
        self.ignores = ignores = []

        for line in ignorelines:
            comment_position = line.find("#")
            # Strip comments.
            if comment_position != -1:
                line = line[:comment_position]

            glob = line.strip()

            # Skip blank lines.
            if not glob:
                continue

            # Normalize path if needed.
            if glob and os.sep != '/' and '/' in glob:
                glob = glob.replace('/', os.sep)

            ignores.append(glob)

    def __call__(self, path):
        """
        Given a filepath, returns wether the path is ignored or not.
        """

        for glob in self.ignores:
            if path.fnmatch(glob):
                return glob

        return False


class IsortError(Exception):
    """
    Indicates an error during isort checks.
    """

    def __init__(self, output=''):
        self.output = output

    def simplified_error(self):
        """
        This helper strips out unneeded diff "header" lines (+++, ---, @@).

        These lines are not needed in this case. In addition, this helper inserts
        a blank line between the error message and the diff output.
        """
        if not self.output:
            return ''

        valid_lines = [
            line
            for line in self.output.splitlines()
            if line.strip().split(' ', 1)[0] not in ('+++', '---', '@@')
        ]

        if len(valid_lines) > 1:
            valid_lines.insert(1, '')

        return '\n'.join(valid_lines)


class IsortItem(pytest.Item, pytest.File):
    """
    py.test Item to run the isort check.
    """

    def __init__(self, path, parent):
        super(IsortItem, self).__init__(path, parent)
        self.add_marker('isort')

    def setup(self):
        # Fetch mtime of file to compare with cache and for writing to cache
        # later on.
        self._mtime = self.fspath.mtime()

        old = self.config._isort_mtimes.get(str(self.fspath), 0)
        if old == self._mtime:
            pytest.skip('file(s) previously passed isort checks')

    def runtest(self):
        # Execute actual isort check.
        found_errors, stdout, stderr = py.io.StdCaptureFD.call(
            isort_check_file, self.fspath)

        if found_errors:
            # Strip diff header, this is not needed when displaying errors.
            raise IsortError(stdout)

        # Update mtime only if test passed otherwise failures
        # would not be re-run next time.
        self.config._isort_mtimes[str(self.fspath)] = self._mtime

    def repr_failure(self, excinfo):
        if excinfo.errisinstance(IsortError):
            # Return the simplified/filtered error output of isort.
            return excinfo.value.simplified_error()

        return super(IsortItem, self).repr_failure(excinfo)

    def reportinfo(self):
        return (self.fspath, -1, 'isort-check')
