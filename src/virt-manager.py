#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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

import os
import os.path
import sys

import logging
import traceback
import signal
import optparse

try:
    # Make sure we have a default '_' implementation, in case something
    # fails before gettext is set up
    __builtins__._ = lambda msg: msg
except:
    pass

def split_list(commastr):
    return [d for d in commastr.split(",") if d]

# These are substituted into code based on --prefix given to configure
appname = "virt-manager"
appversion = "0.9.3"
gettext_app = "virt-manager"
gettext_dir = "/usr/local/share/locale"
virtinst_str = "0.600.2"

asset_dir = "/usr/local/share/virt-manager"
ui_dir = asset_dir
icon_dir = asset_dir + "/icons"
pylib_dir = "/usr/local/share/virt-manager"
pyarchlib_dir = "/usr/local/lib/virt-manager"

default_qemu_user = "root"
rhel_enable_unsupported_opts = bool(int("1"))
preferred_distros = split_list("")

hv_packages = split_list("::KVM_PACKAGES::")
askpass_package = split_list("")
libvirt_packages = split_list("")

logging_setup = False

def _show_startup_error(msg, details):
    from virtManager.error import vmmErrorDialog
    err = vmmErrorDialog()
    title = _("Error starting Virtual Machine Manager")
    err.show_err(title + ": " + msg,
                 details=details,
                 title=title,
                 async=False,
                 debug=False)

def setup_pypath():
    global ui_dir, icon_dir

    # Hack to find assets in local dir for dev purposes
    if os.path.exists(os.getcwd() + "/src/virt-manager.py.in"):
        ui_dir = os.path.join(os.getcwd(), "src")
        icon_dir = os.path.join(os.getcwd(), "icons")
    else:
        sys.path.insert(0, pylib_dir)
        sys.path.insert(0, pyarchlib_dir)


def drop_tty():
    # We fork and setsid so that we drop the controlling
    # tty. This prevents libvirt's SSH tunnels from prompting
    # for user input if SSH keys/agent aren't configured.
    if os.fork() != 0:
        os._exit(0)

    os.setsid()

def drop_stdio():
    # We close STDIN/OUT/ERR since they're generally spewing
    # junk to console when domains are in process of shutting
    # down. Real errors will (hopefully) all be logged to the
    # main log file. This is also again to stop SSH prompting
    # for input
    for fd in range(0, 2):
        try:
            os.close(fd)
        except OSError:
            pass

    os.open(os.devnull, os.O_RDWR)
    os.dup2(0, 1)
    os.dup2(0, 2)

def parse_commandline():
    optParser = optparse.OptionParser(version=appversion,
                                      usage="virt-manager [options]")

    optParser.set_defaults(uuid=None)

    # Generate runtime performance profile stats with hotshot
    optParser.add_option("--profile", dest="profile",
        help=optparse.SUPPRESS_HELP, metavar="FILE")

    optParser.add_option("-c", "--connect", dest="uri",
        help="Connect to hypervisor at URI", metavar="URI")
    optParser.add_option("--debug", action="store_true", dest="debug",
        help="Print debug output to stdout (implies --no-fork)",
        default=False)
    optParser.add_option("--no-dbus", action="store_true", dest="nodbus",
        help="Disable DBus service for controlling UI")
    optParser.add_option("--no-fork", action="store_true", dest="nofork",
        help="Don't fork into background on startup")
    optParser.add_option("--no-conn-autostart", action="store_true",
                         dest="no_conn_auto",
                         help="Do not autostart connections")

    optParser.add_option("--show-domain-creator", action="callback",
        callback=opt_show_cb, dest="show",
        help="Show 'New VM' wizard")
    optParser.add_option("--show-domain-editor", type="string",
        metavar="UUID", action="callback", callback=opt_show_cb,
        help="Show domain details window")
    optParser.add_option("--show-domain-performance", type="string",
        metavar="UUID", action="callback", callback=opt_show_cb,
        help="Show domain performance window")
    optParser.add_option("--show-domain-console", type="string",
        metavar="UUID", action="callback", callback=opt_show_cb,
        help="Show domain graphical console window")
    optParser.add_option("--show-host-summary", action="callback",
       callback=opt_show_cb, help="Show connection details window")

    return optParser.parse_args()


def launch_specific_window(engine, show, uri, uuid):
    if not show:
        return

    logging.debug("Launching requested window '%s'", show)
    if show == 'creator':
        engine.show_domain_creator(uri)
    elif show == 'editor':
        engine.show_domain_editor(uri, uuid)
    elif show == 'performance':
        engine.show_domain_performance(uri, uuid)
    elif show == 'console':
        engine.show_domain_console(uri, uuid)
    elif show == 'summary':
        engine.show_host_summary(uri)

def _conn_state_changed(conn, engine, show, uri, uuid):
    if conn.state == conn.STATE_DISCONNECTED:
        return True
    if conn.state != conn.STATE_ACTIVE:
        return

    launch_specific_window(engine, show, uri, uuid)
    return True

# maps --show-* to engine (ie local instance) methods
def show_engine(engine, show, uri, uuid, no_conn_auto):
    conn = None

    # Do this regardless
    engine.show_manager()

    if uri:
        conn = engine.add_conn(uri)

        if conn and show:
            conn.connect_opt_out("state-changed",
                                 _conn_state_changed,
                                 engine, show, uri, uuid)

        engine.connect_to_uri(uri)

    if not no_conn_auto:
        engine.autostart_conns()

# maps --show-* to remote manager (ie dbus call) methods
def show_remote(managerObj, show, uri, uuid):
    # Do this regardless
    managerObj.show_manager()

    if show or uri or uuid:
        launch_specific_window(managerObj, show, uri, uuid)

def dbus_config(engine):
    """
    Setup dbus interface
    """
    import dbus
    from virtManager.remote import vmmRemote
    bus = None

    if os.getenv("DBUS_STARTER_ADDRESS") is None:
        bus = dbus.SessionBus()
    else:
        bus = dbus.StarterBus()

    dbusProxy = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
    dbusObj = dbus.Interface(dbusProxy, "org.freedesktop.DBus")

    if dbusObj.NameHasOwner("com.redhat.virt.manager"):
        # We're already running, so just talk to existing process
        managerProxy = bus.get_object("com.redhat.virt.manager",
                                      "/com/redhat/virt/manager")
        managerObj = dbus.Interface(managerProxy, "com.redhat.virt.manager")
        return managerObj

    else:
        # Grab the service to allow others to talk to us later
        name = dbus.service.BusName("com.redhat.virt.manager", bus=bus)
        vmmRemote(engine, name)

# Generic OptionParser callback for all --show-* options
# This routine stores UUID to options.uuid for all --show-* options
# where is metavar="UUID" and also sets options.show
def opt_show_cb(option, opt_str, value, parser):
    if option.metavar == "UUID":
        setattr(parser.values, "uuid", value)
    s = str(option)
    show = s[s.rindex('-') + 1:]
    setattr(parser.values, "show", show)

# Run me!
def main():
    setup_pypath()

    import virtManager
    from virtManager import cli

    cli.setup_i18n(gettext_app, gettext_dir)

    # Need to do this before GTK strips args like --sync
    gtk_error = None
    origargs = " ".join(sys.argv[:])

    # Urgh, pygtk merely logs a warning when failing to open
    # the X11 display connection, and lets everything carry
    # on as if all were fine. Ultimately bad stuff happens,
    # so lets catch it here & get the hell out...
    import warnings
    warnings.filterwarnings('error', module='gtk', append=True)
    try:
        import gobject

        # Set program name for gnome shell (before importing gtk, which
        # seems to call set_prgname on its own)
        if hasattr(gobject, "set_prgname"):
            gobject.set_prgname(appname)

        import gtk
        globals()["gtk"] = gtk
    except Warning, e:
        # ...the risk is we catch too much though
        # Damned if we do, damned if we dont :-)(
        gtk_error = str(e)
    except Exception, e:
        gtk_error = e
    warnings.resetwarnings()

    # Need to parse CLI after import gtk, since gtk strips --sync
    (options, ignore) = parse_commandline()

    # Only raise this error after parsing the CLI, so users at least
    # get --help output and CLI validation
    if gtk_error:
        if type(gtk_error) is str:
            raise RuntimeError(_("Unable to initialize GTK: %s") % gtk_error)
        raise gtk_error

    if not hasattr(gtk, "Builder"):
        raise RuntimeError("virt-manager requires GtkBuilder support. "
                           "Your gtk version appears to be too old.")

	#����log�ļ�
    cli.setup_logging(appname, options.debug)
    global logging_setup
    logging_setup = True

    logging.debug("Launched as: %s", origargs)
    logging.debug("GTK version: %s", str(gtk.gtk_version))
    logging.debug("virt-manager version: %s", appversion)
    logging.debug("virtManager import: %s", str(virtManager))

	#���virtinst�汾
    cli.check_virtinst_version(virtinst_str)

    # Add our icon dir to icon theme
    icon_theme = gtk.icon_theme_get_default()
    icon_theme.prepend_search_path(icon_dir)

    gobject.threads_init()

    import dbus
    import dbus.mainloop.glib
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    dbus.mainloop.glib.threads_init()
    import dbus.service

    # Specifically init config/gconf before the fork, so that pam
    # doesn't think we closed the app, therefor robbing us of
    # display access
    import virtManager.config
    import virtManager.util
    config = virtManager.config.vmmConfig(appname, appversion, ui_dir)
    virtManager.util.running_config = config
    config.default_qemu_user = default_qemu_user
    config.rhel6_defaults = rhel_enable_unsupported_opts
    config.preferred_distros = preferred_distros

    config.hv_packages = hv_packages
    config.libvirt_packages = libvirt_packages
    config.askpass_package = askpass_package

    import virtManager.guidiff
    virtManager.guidiff.is_gui(True)

    # Now we've got basic environment up & running we can fork
    if not options.nofork and not options.debug:
        drop_tty()
        drop_stdio()

        # Ignore SIGHUP, otherwise a serial console closing drops the whole app
        signal.signal(signal.SIGHUP, signal.SIG_IGN)

    from virtManager.engine import vmmEngine

    gtk.window_set_default_icon_name(appname)

    if options.show and options.uri == None:
        raise optparse.OptionValueError("can't use --show-* options "
                                        "without --connect")

    engine = vmmEngine()

    if not options.nodbus:
        try:
            managerObj = dbus_config(engine)
            if managerObj:
                # yes, we exit completely now - remote service is in charge
                logging.debug("Connected to already running instance.")
                show_remote(managerObj, options.show,
                            options.uri, options.uuid)
                return
        except:
            # Something went wrong doing dbus setup, just ignore & carry on
            logging.exception("Could not get connection to session bus, "
                              "disabling DBus service")

    # Hook libvirt events into glib main loop
    import virtManager.libvirtglib
    virtManager.libvirtglib.register_event_impl()

    # At this point we're either starting a brand new controlling instance,
    # or the dbus comms to existing instance has failed

    # Finally start the app for real
    show_engine(engine, options.show, options.uri, options.uuid,
                options.no_conn_auto)
    if options.profile != None:
        import hotshot
        prof = hotshot.Profile(options.profile)
        prof.runcall(gtk.main)
        prof.close()
    else:
        gtk.main()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.debug("Received KeyboardInterrupt. Exiting application.")
    except SystemExit:
        raise
    except Exception, run_e:
        if logging_setup:
            logging.exception(run_e)
        if "gtk" not in globals():
            raise
        _show_startup_error(str(run_e), "".join(traceback.format_exc()))
