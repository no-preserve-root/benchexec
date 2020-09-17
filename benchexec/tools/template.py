# This file is part of BenchExec, a framework for reliable benchmarking:
# https://github.com/sosy-lab/benchexec
#
# SPDX-FileCopyrightText: 2007-2020 Dirk Beyer <https://www.sosy-lab.org>
#
# SPDX-License-Identifier: Apache-2.0

"""
This module provides base classes from which tool-info modules need to inherit.
New tool-info modules should inherit from the latest class (BaseTool2),
other base classes are provided for compatibility with older tool-info modules.
The class that a tool-info module provides always has to have the name "Tool".

For more information, please refer to
https://github.com/sosy-lab/benchexec/blob/master/doc/tool-integration.md
"""

from abc import ABCMeta, abstractmethod
from collections import namedtuple
import copy
import os
import logging
import subprocess

import benchexec
import benchexec.result as result
import benchexec.util as util


class UnsupportedFeatureException(benchexec.BenchExecException):
    """
    Raised when a tool or its tool-info module does not support a requested feature.
    """

    pass


class BaseTool2(object, metaclass=ABCMeta):
    """
    This class serves both as a template for tool-info implementations,
    and as an abstract super class for them.
    For writing a new tool info, inherit from this class and override
    the necessary methods (always executable() and name(),
    usually determine_result(), cmdline(), and version(),
    and maybe working_directory() and get_value_from_output(), too).

    In special circumstances, it can make sense to not inherit from this class.
    In such cases the tool-info module's class needs to implement all the methods
    defined here and BaseTool2.register needs to be called with the respective class
    (cf. documentation of abc.ABCMeta.register) to declare compatibility with BaseTool2.
    Note that we might add optional methods (with default implementations) to BaseTool2
    at any time.

    This class is supported since BenchExec 3.2.
    """

    REQUIRED_PATHS = []
    """
    List of path patterns that is used by the default implementation of program_files().
    Not necessary if this method is overwritten.
    """

    # Methods that provide general (run-independent) information about the tool

    @abstractmethod
    def name(self):
        """
        Return the name of the tool, formatted for humans.
        This method always needs to be overriden, and typically just contains

        return "My Toolname"

        @return a non-empty string
        """
        raise NotImplementedError()

    @abstractmethod
    def executable(self):
        """
        Find the path to the executable file that will get executed.
        This method always needs to be overridden,
        and should typically delegate to our utility method find_executable. Example:

        return benchexec.util.find_executable("mytool")

        The path returned should be relative to the current directory.
        @return a string pointing to an executable file
        """
        raise NotImplementedError()

    def version(self, executable):
        """
        Determine a version string for this tool, if available.
        Do not hard-code a version in this function, either extract the version
        from the tool or do not return a version at all.
        There is a helper function `self._version_from_tool`
        that should work with most tools, you only need to extract the version number
        from the returned tool output.
        @return a (possibly empty) string
        """
        return ""

    def _version_from_tool(
        self,
        executable,
        arg="--version",
        use_stderr=False,
        ignore_stderr=False,
        line_prefix=None,
    ):
        """
        Get version of a tool by executing it with argument "--version"
        and returning stdout.
        @param executable: the path to the executable of the tool (typically the result of executable())
        @param arg: an argument to pass to the tool to let it print its version
        @param use_stderr: True if the tool prints version on stderr, False for stdout
        @param line_prefix: if given, search line with this prefix and return only the rest of this line
        @return a (possibly empty) string of output of the tool
        """
        try:
            process = subprocess.Popen(
                [executable, arg], stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            (stdout, stderr) = process.communicate()
        except OSError as e:
            logging.warning(
                "Cannot run {0} to determine version: {1}".format(
                    executable, e.strerror
                )
            )
            return ""
        if stderr and not use_stderr and not ignore_stderr:
            logging.warning(
                "Cannot determine {0} version, error output: {1}".format(
                    executable, util.decode_to_string(stderr)
                )
            )
            return ""
        if process.returncode:
            logging.warning(
                "Cannot determine {0} version, exit code {1}".format(
                    executable, process.returncode
                )
            )
            return ""

        output = util.decode_to_string(stderr if use_stderr else stdout).strip()
        if line_prefix:
            matches = (
                line[len(line_prefix) :].strip()
                for line in output.splitlines()
                if line.startswith(line_prefix)
            )
            output = next(matches, "")
        return output

    def environment(self, executable):
        """
        OPTIONAL, this method is only necessary for tools
        that needs special environment variable, such as a modified PATH.
        However, for usability of the tool it is in general not recommended to require
        additional variables (tool uses outside of BenchExec would need to have them specified
        manually), but instead change the tool such that it does not need additional variables.
        For example, instead of requiring the tool directory to be added to PATH,
        the tool can be changed to call binaries from its own directory directly.
        This also has the benefit of not confusing bundled binaries
        with existing binaries of the system.

        Note that when executing benchmarks under a separate user account (with flag --user),
        the environment of the tool is a fresh almost-empty one.
        This function can be used to set some variables.

        Note that runexec usually overrides the environment variable $HOME and sets it to a fresh
        directory. If your tool relies on $HOME pointing to the real home directory,
        you can use the result of this function to overwrite the value specified by runexec.
        This is not recommended, however, because it means that runs may be influenced
        by files in the home directory, which hinders reproducibility.

        This method returns a dict that contains several further dicts.
        All keys and values have to be strings.
        Currently we support 3 identifiers in the outer dict:

        "keepEnv": If specified, the run gets initialized with a fresh environment and only
                  variables listed in this dict are copied from the system environment
                  (the values in this dict are ignored).
        "newEnv": Before the execution, the values are assigned to the real environment-identifiers.
                  This will override existing values.
        "additionalEnv": Before the execution, the values are appended to the real environment-identifiers.
                  The seperator for the appending must be given in this method,
                  so that the operation "realValue + additionalValue" is a valid value.
                  For example in the PATH-variable the additionalValue starts with a ":".
        @param executable: the path to the executable of the tool (typically the result of executable())
        @return a possibly empty dict with three possibly empty dicts with environment variables in them
        """
        return {}

    def program_files(self, executable):
        """
        OPTIONAL, this method is only necessary for situations when the benchmark environment
        needs to know all files belonging to a tool
        (to transport them to a cloud service, for example).
        Returns a list of files or directories that are necessary to run the tool,
        relative to the current directory.
        The default implementation returns a list with the executable itself
        and all paths that result from expanding patterns in self.REQUIRED_PATHS,
        interpreting the latter as relative to the directory of the executable.
        @return a list of paths as strings
        """
        return [executable] + self._program_files_from_executable(
            executable, self.REQUIRED_PATHS
        )

    def _program_files_from_executable(
        self, executable, required_paths, parent_dir=False
    ):
        """
        Get a list of program files by expanding a list of path patterns
        and interpreting it as relative to the executable.
        This method can be used as helper for implementing the method program_files().
        Contrary to the default implementation of program_files(), this method does not explicitly
        add the executable to the list of returned files, it assumes that required_paths
        contains a path that covers the executable.
        @param executable: the path to the executable of the tool (typically the result of executable())
        @param required_paths: a list of required path patterns
        @param parent_dir: whether required_paths are relative to the directory of executable or the parent directory
        @return a list of paths as strings, suitable for result of program_files()
        """
        base_dir = os.path.dirname(executable)
        if parent_dir:
            base_dir = os.path.join(base_dir, os.path.pardir)
        return util.flatten(
            util.expand_filename_pattern(path, base_dir) for path in required_paths
        )

    def working_directory(self, executable):
        """
        OPTIONAL, this method is only necessary for situations
        when the tool needs a separate working directory.
        @param executable: the path to the executable of the tool (typically the result of executable())
        @return a string pointing to a directory
        """
        return os.curdir

    # Methods for handling individual runs and their results

    def cmdline(self, executable, options, task, rlimits):
        """
        Compose the command line to execute from the name of the executable,
        the user-specified options, and the inputfile to analyze.
        This method can get overridden, if, for example, some options should
        be enabled or if the order of arguments must be changed.

        All paths passed to this method (executable and fields of task)
        are either absolute or have been made relative to the designated working directory.

        @param executable: the path to the executable of the tool (typically the result of executable())
        @param options: a list of options, in the same order as given in the XML-file.
        @param task: An instance of of class Task, e.g., with the input files
        @param rlimits: An instance of class ResourceLimits with the limits for this run
        @return a list of strings that represent the command line to execute
        """
        return [executable, *options, *task.input_files_or_identifier]

    def determine_result(self, exit_code, output, isTimeout):
        """
        Parse the output of the tool and extract the verification result.
        If the tool gave a result, this method needs to return one of the
        benchexec.result.RESULT_* strings.
        Otherwise an arbitrary string can be returned that will be shown to the user
        and should give some indication of the failure reason
        (e.g., "CRASH", "OUT_OF_MEMORY", etc.).
        For tools that do not output some true/false result, benchexec.result.RESULT_DONE
        can be returned (this is also the default implementation).
        BenchExec will then automatically add some more information
        if the tool was killed due to a timeout, segmentation fault, etc.
        @param exit_code: an instance of class benchexec.util.ProcessExitCode
        @param output: a list of strings of output lines of the tool (both stdout and stderr)
        @param isTimeout: whether the result is a timeout
        (useful to distinguish between program killed because of error and timeout)
        @return a non-empty string, usually one of the benchexec.result.RESULT_* constants
        """
        return result.RESULT_DONE

    def get_value_from_output(self, lines, identifier):
        """
        OPTIONAL, extract a statistic value from the output of the tool.
        This value will be added to the resulting tables.
        It may contain HTML code, which will be rendered appropriately in the HTML tables.
        @param lines: The output of the tool as list of lines.
        @param identifier: The user-specified identifier for the statistic item.
        @return a (possibly empty) string, optional with HTML tags
        """

    # Classes that are used in parameters above

    class Task(
        namedtuple(
            "Task", ["input_files_or_empty", "identifier", "property_file", "options"]
        )
    ):
        """
        Represent the task for which the tool should be executed in a run.
        While this class is technically a tuple,
        this should be seen as an implementation detail and the order of elements in the
        tuple should not be considered. New fields may be added in the future.

        Explanation of fields:
        input_files_or_empty: ordered sequence of paths to input files (or directories),
            each relative to the tool's working directory;
            guaranteed to be of type collections.abc.Sequence;
            it is recommended to access input_files or input_files_or_identifier instead
        identifier: name of task when <withoutfile> is used to define the task,
            i.e., when the list of input files is empty, None otherwise
        property_file: path to property file if one is used (relative to the tool's
            working directory) or None otherwise
        options: content of the "options" key in the task-definition file (if present)
        """

        def __new__(cls, input_files, identifier, property_file, options):
            input_files = tuple(input_files)  # make input_files immutable
            assert bool(input_files) != bool(
                identifier
            ), "exactly one is required: input_files=%r identifier=%r" % (
                input_files,
                identifier,
            )
            options = copy.deepcopy(options)  # defensive copy because not immutable
            return super().__new__(cls, input_files, identifier, property_file, options)

        @classmethod
        def with_files(cls, input_files, *, property_file=None, options=None):
            return cls(
                input_files=input_files,
                identifier=None,
                property_file=property_file,
                options=options,
            )

        @classmethod
        def without_files(cls, identifier, *, property_file=None, options=None):
            return cls(
                input_files=[],
                identifier=identifier,
                property_file=property_file,
                options=options,
            )

        @property
        def input_files(self):
            self.require_input_files()
            return self.input_files_or_empty

        @property
        def input_files_or_identifier(self):
            """
            Return either the sequence of input files or a one-element sequence with the
            identifier. Useful for adding either to the command line arguments.
            """
            return self.input_files_or_empty or tuple(self.identifier)

        def require_input_files(self):
            """
            Check that there is at least one path in input_files and raise appropriate
            exception otherwise
            """
            if not self.input_files_or_empty:
                raise UnsupportedFeatureException(
                    "Tool does not support tasks without input files"
                )

    class ResourceLimits(
        namedtuple(
            "ResourceLimits",
            ["cputime", "cputime_hard", "walltime", "memory", "cpu_cores"],
        )
    ):
        """
        Represent resource limits of a run. While this class is technically a tuple,
        this should be seen as an implementation detail and the order of elements in the
        tuple should not be considered. New fields may be added in the future.
        Each field contains a positive int or None, which means no limit.

        Explanation of fields:
        cputime: CPU-time limit in seconds after which the tool will receive
            a termination signal and the result will be counted as timeout
        cputime_hard: CPU-time limit in seconds after which the tool will be killed
            forcibly (always greater or equal than cputime)
        walltime: Wall-time limit in seconds after which the tool will be killed
        memory: Memory limit in bytes
        cpu_cores: Number of CPU cores allowed to be used

        The CPU-time limits will either both have a value of both be None.
        """

        def __new__(
            cls,
            cputime=None,
            cputime_hard=None,
            walltime=None,
            memory=None,
            cpu_cores=None,
        ):
            return super().__new__(
                cls, cputime, cputime_hard, walltime, memory, cpu_cores
            )


class BaseTool(object):
    """
    This class serves both as a template for tool-info implementations,
    and as an abstract super class for them.
    However, for writing a new tool info, it is recommended to inherit from the latest
    class in this module instead of this class.
    Classes that inherit from this class need to override
    the necessary methods (always executable() and name(),
    usually determine_result(), cmdline(), and version(),
    and maybe working_directory() and get_value_from_output(), too).

    Support for tool-info modules based on this class might be dropped in BenchExec 4.0
    or later.
    """

    REQUIRED_PATHS = []
    """
    List of path patterns that is used by the default implementation of program_files().
    Not necessary if this method is overwritten.
    """

    def executable(self):
        """
        Find the path to the executable file that will get executed.
        This method always needs to be overridden,
        and most implementations will look similar to this one.
        The path returned should be relative to the current directory.
        @return a string pointing to an executable file
        """
        return util.find_executable("tool")

    def program_files(self, executable):
        """
        OPTIONAL, this method is only necessary for situations when the benchmark environment
        needs to know all files belonging to a tool
        (to transport them to a cloud service, for example).
        Returns a list of files or directories that are necessary to run the tool,
        relative to the current directory.
        The default implementation returns a list with the executable itself
        and all paths that result from expanding patterns in self.REQUIRED_PATHS,
        interpreting the latter as relative to the directory of the executable.
        @return a list of paths as strings
        """
        return [executable] + self._program_files_from_executable(
            executable, self.REQUIRED_PATHS
        )

    def _program_files_from_executable(
        self, executable, required_paths, parent_dir=False
    ):
        """
        Get a list of program files by expanding a list of path patterns
        and interpreting it as relative to the executable.
        This method can be used as helper for implementing the method program_files().
        Contrary to the default implementation of program_files(), this method does not explicitly
        add the executable to the list of returned files, it assumes that required_paths
        contains a path that covers the executable.
        @param executable: the path to the executable of the tool (typically the result of executable())
        @param required_paths: a list of required path patterns
        @param parent_dir: whether required_paths are relative to the directory of executable or the parent directory
        @return a list of paths as strings, suitable for result of program_files()
        """
        base_dir = os.path.dirname(executable)
        if parent_dir:
            base_dir = os.path.join(base_dir, os.path.pardir)
        return util.flatten(
            util.expand_filename_pattern(path, base_dir) for path in required_paths
        )

    def version(self, executable):
        """
        Determine a version string for this tool, if available.
        Do not hard-code a version in this function, either extract the version
        from the tool or do not return a version at all.
        There is a helper function `self._version_from_tool`
        that should work with most tools, you only need to extract the version number
        from the returned tool output.
        @return a (possibly empty) string
        """
        return ""

    def _version_from_tool(
        self,
        executable,
        arg="--version",
        use_stderr=False,
        ignore_stderr=False,
        line_prefix=None,
    ):
        """
        Get version of a tool by executing it with argument "--version"
        and returning stdout.
        @param executable: the path to the executable of the tool (typically the result of executable())
        @param arg: an argument to pass to the tool to let it print its version
        @param use_stderr: True if the tool prints version on stderr, False for stdout
        @param line_prefix: if given, search line with this prefix and return only the rest of this line
        @return a (possibly empty) string of output of the tool
        """
        try:
            process = subprocess.Popen(
                [executable, arg], stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            (stdout, stderr) = process.communicate()
        except OSError as e:
            logging.warning(
                "Cannot run {0} to determine version: {1}".format(
                    executable, e.strerror
                )
            )
            return ""
        if stderr and not use_stderr and not ignore_stderr:
            logging.warning(
                "Cannot determine {0} version, error output: {1}".format(
                    executable, util.decode_to_string(stderr)
                )
            )
            return ""
        if process.returncode:
            logging.warning(
                "Cannot determine {0} version, exit code {1}".format(
                    executable, process.returncode
                )
            )
            return ""

        output = util.decode_to_string(stderr if use_stderr else stdout).strip()
        if line_prefix:
            matches = (
                line[len(line_prefix) :].strip()
                for line in output.splitlines()
                if line.startswith(line_prefix)
            )
            output = next(matches, "")
        return output

    def name(self):
        """
        Return the name of the tool, formatted for humans.
        This function should always be overriden.
        @return a non-empty string
        """
        return "UNKOWN"

    def cmdline(self, executable, options, tasks, propertyfile=None, rlimits={}):
        """
        Compose the command line to execute from the name of the executable,
        the user-specified options, and the inputfile to analyze.
        This method can get overridden, if, for example, some options should
        be enabled or if the order of arguments must be changed.

        All paths passed to this method (executable, tasks, and propertyfile)
        are either absolute or have been made relative to the designated working directory.

        @param executable: the path to the executable of the tool (typically the result of executable())
        @param options: a list of options, in the same order as given in the XML-file.
        @param tasks: a list of tasks, that should be analysed with the tool in one run.
                            A typical run has only one input file, but there can be more than one.
        @param propertyfile: contains a specification for the verifier (optional, not always present).
        @param rlimits: This dictionary contains resource-limits for a run,
                        for example: time-limit, soft-time-limit, hard-time-limit, memory-limit, cpu-core-limit.
                        All entries in rlimits are optional, so check for existence before usage!
        @return a list of strings that represent the command line to execute
        """
        return [executable] + options + tasks

    def determine_result(self, returncode, returnsignal, output, isTimeout):
        """
        Parse the output of the tool and extract the verification result.
        If the tool gave a result, this method needs to return one of the
        benchexec.result.RESULT_* strings.
        Otherwise an arbitrary string can be returned that will be shown to the user
        and should give some indication of the failure reason
        (e.g., "CRASH", "OUT_OF_MEMORY", etc.).
        For tools that do not output some true/false result, benchexec.result.RESULT_DONE
        can be returned (this is also the default implementation).
        BenchExec will then automatically add some more information
        if the tool was killed due to a timeout, segmentation fault, etc.
        @param returncode: the exit code of the program, 0 if the program was killed
        @param returnsignal: the signal that killed the program, 0 if program exited itself
        @param output: a list of strings of output lines of the tool (both stdout and stderr)
        @param isTimeout: whether the result is a timeout
        (useful to distinguish between program killed because of error and timeout)
        @return a non-empty string, usually one of the benchexec.result.RESULT_* constants
        """
        return result.RESULT_DONE

    def get_value_from_output(self, lines, identifier):
        """
        OPTIONAL, extract a statistic value from the output of the tool.
        This value will be added to the resulting tables.
        It may contain HTML code, which will be rendered appropriately in the HTML tables.
        @param lines: The output of the tool as list of lines.
        @param identifier: The user-specified identifier for the statistic item.
        @return a (possibly empty) string, optional with HTML tags
        """

    def working_directory(self, executable):
        """
        OPTIONAL, this method is only necessary for situations
        when the tool needs a separate working directory.
        @param executable: the path to the executable of the tool (typically the result of executable())
        @return a string pointing to a directory
        """
        return os.curdir

    def environment(self, executable):
        """
        OPTIONAL, this method is only necessary for tools
        that needs special environment variable, such as a modified PATH.
        However, for usability of the tool it is in general not recommended to require
        additional variables (tool uses outside of BenchExec would need to have them specified
        manually), but instead change the tool such that it does not need additional variables.
        For example, instead of requiring the tool directory to be added to PATH,
        the tool can be changed to call binaries from its own directory directly.
        This also has the benefit of not confusing bundled binaries
        with existing binaries of the system.

        Note that when executing benchmarks under a separate user account (with flag --user),
        the environment of the tool is a fresh almost-empty one.
        This function can be used to set some variables.

        Note that runexec usually overrides the environment variable $HOME and sets it to a fresh
        directory. If your tool relies on $HOME pointing to the real home directory,
        you can use the result of this function to overwrite the value specified by runexec.
        This is not recommended, however, because it means that runs may be influenced
        by files in the home directory, which hinders reproducibility.

        This method returns a dict that contains several further dicts.
        All keys and values have to be strings.
        Currently we support 3 identifiers in the outer dict:

        "keepEnv": If specified, the run gets initialized with a fresh environment and only
                  variables listed in this dict are copied from the system environment
                  (the values in this dict are ignored).
        "newEnv": Before the execution, the values are assigned to the real environment-identifiers.
                  This will override existing values.
        "additionalEnv": Before the execution, the values are appended to the real environment-identifiers.
                  The seperator for the appending must be given in this method,
                  so that the operation "realValue + additionalValue" is a valid value.
                  For example in the PATH-variable the additionalValue starts with a ":".
        @param executable: the path to the executable of the tool (typically the result of executable())
        @return a possibly empty dict with three possibly empty dicts with environment variables in them
        """
        return {}
