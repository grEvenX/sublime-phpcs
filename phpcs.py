import datetime
import os
import re
import subprocess
import threading
import time
import sublime
import sublime_plugin
import HTMLParser


settings = sublime.load_settings('phpcs.sublime-settings')

class Pref:
    @staticmethod
    def load():
        Pref.show_debug = settings.get('show_debug', False)
        Pref.extensions_to_execute = settings.get('extensions_to_execute', ['php'])
        Pref.phpcs_php_path = settings.get('phpcs_php_path', '')
        Pref.phpcs_additional_args = settings.get('phpcs_additional_args', {})
        Pref.phpcs_execute_on_save = bool(settings.get('phpcs_execute_on_save'))
        Pref.phpcs_show_errors_on_save = bool(settings.get('phpcs_show_errors_on_save'))
        Pref.phpcs_show_gutter_marks = bool(settings.get('phpcs_show_gutter_marks'))
        Pref.phpcs_show_errors_in_status = bool(settings.get('phpcs_show_errors_in_status'))
        Pref.phpcs_show_quick_panel = bool(settings.get('phpcs_show_quick_panel'))
        Pref.phpcs_sniffer_run = bool(settings.get('phpcs_sniffer_run'))
        Pref.phpcs_linter_run = bool(settings.get('phpcs_linter_run'))
        Pref.phpcs_linter_regex = settings.get('phpcs_linter_regex')
        Pref.phpcs_executable_path = settings.get('phpcs_executable_path', '')
        Pref.phpmd_run = settings.get('phpmd_run')
        Pref.phpmd_executable_path = settings.get('phpmd_executable_path', '')
        Pref.phpmd_additional_args = settings.get('phpmd_additional_args')

Pref.load()

[settings.add_on_change(setting, Pref.load) for setting in [
    'show_debug',
    'extensions_to_execute',
    'phpcs_php_path',
    'phpcs_additional_args',
    'phpcs_execute_on_save',
    'phpcs_show_errors_on_save',
    'phpcs_show_gutter_marks',
    'phpcs_show_errors_in_status',
    'phpcs_show_quick_panel',
    'phpcs_sniffer_run',
    'phpcs_linter_run',
    'phpcs_linter_regex',
    'phpcs_executable_path',
    'phpmd_run',
    'phpmd_executable_path',
    'phpmd_additional_args']]


def debug_message(msg):
    if Pref.show_debug == True:
        print "[Phpcs] " + msg


class CheckstyleError():
    """Represents an error that needs to be displayed on the UI for the user"""
    def __init__(self, line, message):
        self.line = line
        self.message = message

    def get_line(self):
        return self.line

    def get_message(self):
        data = self.message
        try:
            data = data.decode('utf-8')
        except UnicodeDecodeError:
            data = data.decode(sublime.active_window().active_view().settings().get('fallback_encoding'))
        return HTMLParser.HTMLParser().unescape(data)

    def set_point(self, point):
        self.point = point

    def get_point(self):
        return self.point


class ShellCommand():
    """Base class for shelling out a command to the terminal"""
    def __init__(self):
        self.error_list = []

    def get_errors(self, path):
        self.execute(path)
        return self.error_list

    def shell_out(self, cmd):
        data = None
        debug_message(' '.join(cmd))

        if sublime.platform() == "windows":
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        else:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)

        if proc.stdout:
            data = proc.communicate()[0]

        return data

    def execute(self, path):
        debug_message('Command not implemented')


class Sniffer(ShellCommand):
    """Concrete class for PHP_CodeSniffer"""
    def execute(self, path):
        if Pref.phpcs_sniffer_run != True:
            return

        if Pref.phpcs_executable_path != "":
            args = [Pref.phpcs_executable_path]
        else:
            args = ['phpcs']

        args.append("--report=checkstyle")

        # Add the additional arguments from the settings file to the command
        for key, value in Pref.phpcs_additional_args.items():
            arg = key
            if value != "":
                arg += "=" + value
            args.append(arg)

        args.append(os.path.normpath(path))
        self.parse_report(args)

    def parse_report(self, args):
        report = self.shell_out(args)
        debug_message(report)
        lines = re.finditer('.*line="(?P<line>\d+)" column="(?P<column>\d+)" severity="(?P<severity>\w+)" message="(?P<message>.*)" source', report)

        for line in lines:
            error = CheckstyleError(line.group('line'), line.group('message'))
            self.error_list.append(error)


class MessDetector(ShellCommand):
    """Concrete class for PHP Mess Detector"""
    def execute(self, path):
        if Pref.phpmd_run != True:
            return

        if Pref.phpmd_executable_path != "":
            args = [Pref.phpmd_executable_path]
        else:
            args = ['phpmd']

        args.append(os.path.normpath(path))
        args.append('text')

        for key, value in Pref.phpmd_additional_args.items():
            arg = key
            if value != "":
                arg += "=" + value
            args.append(arg)

        self.parse_report(args)

    def parse_report(self, args):
        report = self.shell_out(args)
        debug_message(report)
        lines = re.finditer('.*:(?P<line>\d+)[ \t]+(?P<message>.*)', report)

        for line in lines:
            error = CheckstyleError(line.group('line'), line.group('message'))
            self.error_list.append(error)


class Linter(ShellCommand):
    """Content class for php -l"""
    def execute(self, path):
        if Pref.phpcs_linter_run != True:
            return

        if Pref.phpcs_php_path != "":
            args = [Pref.phpcs_php_path]
        else:
            args = ['php']

        args.append("-l")
        args.append("-d display_errors=On")
        args.append(os.path.normpath(path))

        self.parse_report(args)

    def parse_report(self, args):
        report = self.shell_out(args)
        debug_message(report)
        line = re.search(Pref.phpcs_linter_regex, report)
        if line != None:
            error = CheckstyleError(line.group('line'), line.group('message'))
            self.error_list.append(error)


class PhpcsCommand():
    """Main plugin class for building the checkstyle report"""

    # Class variable, stores the instances.
    instances = {}

    @staticmethod
    def instance(view, allow_new=True):
        '''Return the last-used instance for a given view.'''
        view_id = view.id()
        if view_id not in PhpcsCommand.instances:
            if not allow_new:
                return False
            PhpcsCommand.instances[view_id] = PhpcsCommand(view.window())
        return PhpcsCommand.instances[view_id]

    def __init__(self, window):
        self.window = window
        self.checkstyle_reports = []
        self.report = []
        self.event = None
        self.error_lines = {}
        self.error_list = []
        self.shell_commands = ['Linter', 'Sniffer', 'MessDetector']

    def run(self, path, event=None):
        self.event = event
        self.checkstyle_reports = []
        self.checkstyle_reports.append(['Linter', Linter().get_errors(path), 'cross'])
        self.checkstyle_reports.append(['Sniffer', Sniffer().get_errors(path), 'dot'])
        self.checkstyle_reports.append(['MessDetector', MessDetector().get_errors(path), 'dot'])
        sublime.set_timeout(self.generate, 0)

    def clear_sniffer_marks(self):
        for region in self.shell_commands:
            self.window.active_view().erase_regions(region)

    def set_status_bar(self):
        if not Pref.phpcs_show_errors_in_status:
            return

        if self.window.active_view().is_scratch():
            return

        line = self.window.active_view().rowcol(self.window.active_view().sel()[0].end())[0]
        errors = self.get_errors(line)
        if errors:
            self.window.active_view().set_status('Phpcs', errors)
        else:
            self.window.active_view().erase_status('Phpcs')


    def generate(self):
        self.error_list = []
        region_set = []
        self.error_lines = {}

        for shell_command, report, icon in self.checkstyle_reports:
            self.window.active_view().erase_regions('checkstyle')
            self.window.active_view().erase_regions(shell_command)

            debug_message(shell_command + ' found ' + str(len(report)) + ' errors')
            for error in report:
                line = int(error.get_line())
                pt = self.window.active_view().text_point(line - 1, 0)
                region_set.append(sublime.Region(pt))
                self.error_list.append('(' + str(line) + ') ' + error.get_message())
                error.set_point(pt)
                self.report.append(error)
                self.error_lines[line] = error.get_message()

            if len(self.error_list) > 0:
                if Pref.phpcs_show_gutter_marks == True:
                    self.window.active_view().add_regions(shell_command, region_set, shell_command, icon)

        if Pref.phpcs_show_quick_panel == True:
            # Skip showing the errors if we ran on save, and the option isn't set.
            if self.event == 'on_save' and not Pref.phpcs_show_errors_on_save:
                return
            self.show_quick_panel()

    def show_quick_panel(self):
        self.window.show_quick_panel(self.error_list, self.on_quick_panel_done)

    def on_quick_panel_done(self, picked):
        if picked == -1:
            return

        pt = self.report[picked].get_point()
        self.window.active_view().sel().clear()
        self.window.active_view().sel().add(sublime.Region(pt))
        self.window.active_view().show(pt)
        self.set_status_bar()

    def get_errors(self, line):
        if not line + 1 in self.error_lines:
            return False

        return self.error_lines[line + 1]


class PhpcsTextBase(sublime_plugin.TextCommand):
    """Base class for Text commands in the plugin, mainly here to check php files"""
    description = ''

    def run(self, args):
        debug_message('Not implemented')

    def description(self):
        if not PhpcsTextBase.should_execute(self.view):
            return "Invalid file format"
        else:
            return description

    @staticmethod
    def should_execute(view):
        if view.file_name() != None:
            ext = os.path.splitext(view.file_name())[1]
            result = ext[1:] in Pref.extensions_to_execute
            return result

        return False


class PhpcsSniffThisFile(PhpcsTextBase):
    """Command to sniff the open file"""
    description = 'Sniff this file...'

    def run(self, args):
        cmd = PhpcsCommand.instance(self.view)
        cmd.run(self.view.file_name())

    def is_enabled(self):
        return PhpcsTextBase.should_execute(self.view)


class PhpcsShowPreviousErrors(PhpcsTextBase):
    '''Command to show the previous sniff errors.'''
    description = 'Display sniff errors...'

    def run(self, args):
        cmd = PhpcsCommand.instance(self.view, False)
        cmd.show_quick_panel()

    def is_enabled(self):
        '''This command is only enabled if it's a PHP buffer with previous errors.'''
        return PhpcsTextBase.should_execute(self.view) \
            and PhpcsCommand.instance(self.view, False) \
            and len(PhpcsCommand.instance(self.view, False).error_list)


class PhpcsClearSnifferMarksCommand(PhpcsTextBase):
    """Command to clear the sniffer marks from the view"""
    description = 'Clear sniffer marks...'

    def run(self, args):
        cmd = PhpcsCommand.instance(self.view)
        cmd.clear_sniffer_marks()

    def is_enabled(self):
        return PhpcsTextBase.should_execute(self.view)


class PhpcsEventListener(sublime_plugin.EventListener):
    """Event listener for the plugin"""
    def on_post_save(self, view):
        if Pref.phpcs_execute_on_save == True:
            if PhpcsTextBase.should_execute(view):
                cmd = PhpcsCommand.instance(view)
                thread = threading.Thread(target=cmd.run, args=(view.file_name(), 'on_save'))
                thread.start()

    def on_selection_modified(self, view):
        if not PhpcsTextBase.should_execute(view):
            return

        cmd = PhpcsCommand.instance(view, False)
        if isinstance(cmd, PhpcsCommand):
            cmd.set_status_bar()
