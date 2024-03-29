# virt-manager-tui.py - Copyright (C) 2010 Red Hat, Inc.
# Written by Darryl L. Pierce, <dpierce@redhat.com>.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.
#

from newt_syrup.dialogscreen import DialogScreen

import logging
import os
import sys
import traceback
import optparse

# These are substituted into code based on --prefix given to configure
appname = "virt-manager-tui"
appversion = "0.9.3"
gettext_app = "virt-manager"
gettext_dir = "/usr/local/share/locale"
virtinst_str = "0.600.2"
pylib_dir = "/usr/local/share/virt-manager"
pyarchlib_dir = "/usr/local/lib/virt-manager"

def setup_pypath():
    # Hack to find assets in local dir for dev purposes
    if os.path.exists(os.getcwd() + "/src/virt-manager.py.in"):
        sys.path.insert(0, os.path.join(os.getcwd(),
                                     "/src/virtManagerTui/importblacklist"))
    else:
        sys.path.insert(0, pylib_dir)
        sys.path.insert(0, pyarchlib_dir)

def parse_commandline():
    optParser = optparse.OptionParser(version=appversion)

    optParser.add_option("-c", "--connect", dest="uri",
        help="Connect to hypervisor at URI", metavar="URI")
    optParser.add_option("--debug", action="store_true", dest="debug",
        help="Print debug output to stdout (implies --no-fork)",
        default=False)

    return optParser.parse_args()

def _show_startup_error(message, details):
    errordlg = DialogScreen("Error Starting Virtual Machine Manager",
                            message + "\n\n" + details)
    errordlg.show()

def main():
    setup_pypath()

    import virtManager
    from virtManager import cli

    cli.setup_i18n(gettext_app, gettext_dir)

    (options, ignore) = parse_commandline()
    cli.setup_logging(appname, options.debug)

    logging.debug("Launched as: %s", " ".join(sys.argv[:]))
    logging.debug("virtManager import: %s", str(virtManager))

    cli.check_virtinst_version(virtinst_str)

    import virtManager.guidiff
    virtManager.guidiff.is_gui(False)

    # Hack in the default URI for this instance of the tui
    if options.uri:
        import virtManagerTui.libvirtworker
        virtManagerTui.libvirtworker.default_url = options.uri

    # start the app
    from virtManagerTui.mainmenu import MainMenu
    MainMenu()

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception, error:
        logging.exception(error)
        _show_startup_error(str(error), "".join(traceback.format_exc()))
