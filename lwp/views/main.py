# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

import os
import re
import time
import socket
import subprocess

from flask import Blueprint, request, session, g, redirect, url_for, abort, render_template, flash, jsonify

import lwp
import lwp.lxclite as lxc
from lwp.utils import query_db, if_logged_in, get_bucket_token, hash_passwd, config
from lwp.views.auth import AUTH

# TODO: see if we can move this block somewhere better
try:
    USE_BUCKET = config.getboolean('global', 'buckets')
    BUCKET_HOST = config.get('buckets', 'buckets_host')
    BUCKET_PORT = config.get('buckets', 'buckets_port')
except:
    USE_BUCKET = False
    print("- Bucket feature disabled")


storage_repos = config.items('storage_repository')

# Flask module
mod = Blueprint('main', __name__)


@mod.route('/')
@mod.route('/home')
@if_logged_in()
def home():
    """
    home page function
    """
    listx = lxc.listx()
    containers_all = []

    for status in ('RUNNING', 'FROZEN', 'STOPPED'):
        containers_by_status = []

        for container in listx[status]:
            containers_by_status.append({
                'name': container,
                'memusg': lwp.memory_usage(container),
                'settings': lwp.get_container_settings(container),
                'ipv4': lxc.get_ipv4(container),
                'bucket': get_bucket_token(container)
            })
        containers_all.append({
            'status': status.lower(),
            'containers': containers_by_status
        })

    return render_template('index.html', containers=lxc.ls(), containers_all=containers_all, dist=lwp.check_ubuntu(), host=socket.gethostname(), templates=lwp.get_templates_list(), storage_repos=storage_repos, auth=AUTH)


@mod.route('/about')
@if_logged_in()
def about():
    """
    about page
    """
    return render_template('about.html', containers=lxc.ls(), version=lwp.check_version())


@mod.route('/<container>/edit', methods=['POST', 'GET'])
@if_logged_in()
def edit(container=None):
    """
    edit containers page and actions if form post request
    """
    host_memory = lwp.host_memory_usage()
    cfg = lwp.get_container_settings(container)
    # read config also from databases
    cfg['bucket'] = get_bucket_token(container)

    if request.method == 'POST':
        ip_regex = '(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?).(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?).(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?).(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(/(3[0-2]|[12]?[0-9]))?'
        info = lxc.info(container)

        form = {}
        form['type'] = request.form['type']
        form['link'] = request.form['link']
        try:
            form['flags'] = request.form['flags']
        except KeyError:
            form['flags'] = 'down'
        form['hwaddr'] = request.form['hwaddress']
        form['rootfs'] = request.form['rootfs']
        form['utsname'] = request.form['hostname']
        form['ipv4'] = request.form['ipaddress']
        form['memlimit'] = request.form['memlimit']
        form['swlimit'] = request.form['swlimit']
        form['cpus'] = request.form['cpus']
        form['shares'] = request.form['cpushares']
        form['bucket'] = request.form['bucket']
        try:
            form['autostart'] = request.form['autostart']
        except KeyError:
            form['autostart'] = False

        if form['utsname'] != cfg['utsname'] and re.match('(?!^containers$)|^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$', form['utsname']):
            lwp.push_config_value('lxc.utsname', form['utsname'], container=container)
            flash(u'Hostname updated for %s!' % container, 'success')

        if form['flags'] != cfg['flags'] and re.match('^(up|down)$', form['flags']):
            lwp.push_config_value('lxc.network.flags', form['flags'], container=container)
            flash(u'Network flag updated for %s!' % container, 'success')

        if form['type'] != cfg['type'] and re.match('^\w+$', form['type']):
            lwp.push_config_value('lxc.network.type', form['type'], container=container)
            flash(u'Link type updated for %s!' % container, 'success')

        if form['link'] != cfg['link'] and re.match('^[a-zA-Z0-9_-]+$', form['link']):
            lwp.push_config_value('lxc.network.link', form['link'], container=container)
            flash(u'Link name updated for %s!' % container, 'success')

        if form['hwaddr'] != cfg['hwaddr'] and re.match('^([a-fA-F0-9]{2}[:|\-]?){6}$', form['hwaddr']):
            lwp.push_config_value('lxc.network.hwaddr', form['hwaddr'], container=container)
            flash(u'Hardware address updated for %s!' % container, 'success')

        if (not form['ipv4'] and form['ipv4'] != cfg['ipv4']) or (form['ipv4'] != cfg['ipv4'] and re.match('^%s$' % ip_regex, form['ipv4'])):
            lwp.push_config_value('lxc.network.ipv4', form['ipv4'], container=container)
            flash(u'IP address updated for %s!' % container, 'success')

        if form['memlimit'] != cfg['memlimit'] and form['memlimit'].isdigit() and int(form['memlimit']) <= int(host_memory['total']):
            if int(form['memlimit']) == int(host_memory['total']):
                form['memlimit'] = ''

            if form['memlimit'] != cfg['memlimit']:
                lwp.push_config_value('lxc.cgroup.memory.limit_in_bytes', form['memlimit'], container=container)
                if info["state"].lower() != 'stopped':
                    lxc.cgroup(container, 'lxc.cgroup.memory.limit_in_bytes', form['memlimit'])
                flash(u'Memory limit updated for %s!' % container, 'success')

        if form['swlimit'] != cfg['swlimit'] and form['swlimit'].isdigit() and int(form['swlimit']) <= int(host_memory['total'] * 2):
            if int(form['swlimit']) == int(host_memory['total'] * 2):
                form['swlimit'] = ''

            if form['swlimit'].isdigit():
                form['swlimit'] = int(form['swlimit'])

            if form['memlimit'].isdigit():
                form['memlimit'] = int(form['memlimit'])

            if (form['memlimit'] == '' and form['swlimit'] != '') or (form['memlimit'] > form['swlimit'] and form['swlimit'] != ''):
                flash(u'Can\'t assign swap memory lower than the memory limit', 'warning')

            elif form['swlimit'] != cfg['swlimit'] and form['memlimit'] <= form['swlimit']:
                lwp.push_config_value('lxc.cgroup.memory.memsw.limit_in_bytes', form['swlimit'], container=container)
                if info["state"].lower() != 'stopped':
                    lxc.cgroup(container, 'lxc.cgroup.memory.memsw.limit_in_bytes', form['swlimit'])
                flash(u'Swap limit updated for %s!' % container, 'success')

        if (not form['cpus'] and form['cpus'] != cfg['cpus']) or (form['cpus'] != cfg['cpus'] and re.match('^[0-9,-]+$', form['cpus'])):
            lwp.push_config_value('lxc.cgroup.cpuset.cpus', form['cpus'], container=container)
            if info["state"].lower() != 'stopped':
                    lxc.cgroup(container, 'lxc.cgroup.cpuset.cpus', form['cpus'])
            flash(u'CPUs updated for %s!' % container, 'success')

        if (not form['shares'] and form['shares'] != cfg['shares']) or (form['shares'] != cfg['shares'] and re.match('^[0-9]+$', form['shares'])):
            lwp.push_config_value('lxc.cgroup.cpu.shares', form['shares'], container=container)
            if info["state"].lower() != 'stopped':
                    lxc.cgroup(container, 'lxc.cgroup.cpu.shares', form['shares'])
            flash(u'CPU shares updated for %s!' % container, 'success')

        if form['rootfs'] != cfg['rootfs'] and re.match('^[a-zA-Z0-9_/\-]+', form['rootfs']):
            lwp.push_config_value('lxc.rootfs', form['rootfs'], container=container)
            flash(u'Rootfs updated!' % container, 'success')

        if bool(form['autostart']) != bool(cfg['auto']):
            lwp.push_config_value('lxc.start.auto', 1 if form['autostart'] else 0, container=container)
            flash(u'Autostart saved for %s' % container, 'success')

        if form['bucket'] != cfg['bucket']:
            g.db.execute("INSERT INTO machine(machine_name, bucket_token) VALUES (?, ?)", [container, form['bucket']])
            g.db.commit()
            flash(u'Bucket config for %s saved!' % container, 'success')

    info = lxc.info(container)
    status = info['state']
    pid = info['pid']

    infos = {'status': status, 'pid': pid, 'memusg': lwp.memory_usage(container)}
    return render_template('edit.html', containers=lxc.ls(), container=container, infos=infos, settings=cfg, host_memory=host_memory, storage_repos=storage_repos)


@mod.route('/settings/lxc-net', methods=['POST', 'GET'])
@if_logged_in()
def lxc_net():
    """
    lxc-net (/etc/default/lxc) settings page and actions if form post request
    """
    if session['su'] != 'Yes':
        return abort(403)

    if request.method == 'POST':
        if lxc.running() == []:
            cfg = lwp.get_net_settings()
            ip_regex = '(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?).(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?).(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?).(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)'

            form = {}
            for key in ['bridge', 'address', 'netmask', 'network', 'range', 'max']:
                form[key] = request.form.get(key, None)
            form['use'] = request.form.get('use', None)

            if form['use'] != cfg['use']:
                lwp.push_net_value('USE_LXC_BRIDGE', 'true' if form['use'] else 'false')

            if form['bridge'] and form['bridge'] != cfg['bridge'] and re.match('^[a-zA-Z0-9_-]+$', form['bridge']):
                lwp.push_net_value('LXC_BRIDGE', form['bridge'])

            if form['address'] and form['address'] != cfg['address'] and re.match('^%s$' % ip_regex, form['address']):
                lwp.push_net_value('LXC_ADDR', form['address'])

            if form['netmask'] and form['netmask'] != cfg['netmask'] and re.match('^%s$' % ip_regex, form['netmask']):
                lwp.push_net_value('LXC_NETMASK', form['netmask'])

            if form['network'] and form['network'] != cfg['network'] and re.match('^%s(?:/\d{1,2}|)$' % ip_regex, form['network']):
                lwp.push_net_value('LXC_NETWORK', form['network'])

            if form['range'] and form['range'] != cfg['range'] and re.match('^%s,%s$' % (ip_regex, ip_regex), form['range']):
                lwp.push_net_value('LXC_DHCP_RANGE', form['range'])

            if form['max'] and form['max'] != cfg['max'] and re.match('^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$', form['max']):
                lwp.push_net_value('LXC_DHCP_MAX', form['max'])

            if lwp.net_restart() == 0:
                flash(u'LXC Network settings applied successfully!', 'success')
            else:
                flash(u'Failed to restart LXC networking.', 'error')
        else:
            flash(u'Stop all containers before restart lxc-net.', 'warning')
    return render_template('lxc-net.html', containers=lxc.ls(), cfg=lwp.get_net_settings(), running=lxc.running())


@mod.route('/lwp/users', methods=['POST', 'GET'])
@if_logged_in()
def lwp_users():
    """
    returns users and get posts request : can edit or add user in page.
    this funtction uses sqlite3
    """
    if session['su'] != 'Yes':
        return abort(403)

    if (AUTH == 'ldap'):
        return abort(403, 'You are using ldap as AUTH backend.')

    try:
        trash = request.args.get('trash')
    except KeyError:
        trash = 0

    su_users = query_db("SELECT COUNT(id) as num FROM users WHERE su='Yes'", [], one=True)

    if request.args.get('token') == session.get('token') and int(trash) == 1 and request.args.get('userid') and request.args.get('username'):
        nb_users = query_db("SELECT COUNT(id) as num FROM users", [], one=True)

        if nb_users['num'] > 1:
            if su_users['num'] <= 1:
                su_user = query_db("SELECT username FROM users WHERE su='Yes'", [], one=True)

                if su_user['username'] == request.args.get('username'):
                    flash(u'Can\'t delete the last admin user : %s' % request.args.get('username'), 'error')
                    return redirect(url_for('main.lwp_users'))

            g.db.execute("DELETE FROM users WHERE id=? AND username=?", [request.args.get('userid'), request.args.get('username')])
            g.db.commit()
            flash(u'Deleted %s' % request.args.get('username'), 'success')
            return redirect(url_for('main.lwp_users'))

        flash(u'Can\'t delete the last user!', 'error')
        return redirect(url_for('main.lwp_users'))

    if request.method == 'POST':
        users = query_db('SELECT id, name, username, su FROM users ORDER BY id ASC')

        if request.form['newUser'] == 'True':
            if not request.form['username'] in [user['username'] for user in users]:
                if re.match('^\w+$', request.form['username']) and request.form['password1']:
                    if request.form['password1'] == request.form['password2']:
                        if request.form['name']:
                            if re.match('[a-z A-Z0-9]{3,32}', request.form['name']):
                                g.db.execute("INSERT INTO users (name, username, password) VALUES (?, ?, ?)", [request.form['name'], request.form['username'], hash_passwd(request.form['password1'])])
                                g.db.commit()
                            else:
                                flash(u'Invalid name!', 'error')
                        else:
                            g.db.execute("INSERT INTO users (username, password) VALUES (?, ?)", [request.form['username'], hash_passwd(request.form['password1'])])
                            g.db.commit()

                        flash(u'Created %s' % request.form['username'], 'success')
                    else:
                        flash(u'No password match', 'error')
                else:
                    flash(u'Invalid username or password!', 'error')
            else:
                flash(u'Username already exist!', 'error')

        elif request.form['newUser'] == 'False':
            if request.form['password1'] == request.form['password2']:
                if re.match('[a-z A-Z0-9]{3,32}', request.form['name']):
                    if su_users['num'] <= 1:
                        su = 'Yes'
                    else:
                        try:
                            su = request.form['su']
                        except KeyError:
                            su = 'No'

                    if not request.form['name']:
                        g.db.execute("UPDATE users SET name='', su=? WHERE username=?", [su, request.form['username']])
                        g.db.commit()
                    elif request.form['name'] and not request.form['password1'] and not request.form['password2']:
                        g.db.execute("UPDATE users SET name=?, su=? WHERE username=?", [request.form['name'], su, request.form['username']])
                        g.db.commit()
                    elif request.form['name'] and request.form['password1'] and request.form['password2']:
                        g.db.execute("UPDATE users SET name=?, password=?, su=? WHERE username=?", [request.form['name'], hash_passwd(request.form['password1']), su, request.form['username']])
                        g.db.commit()
                    elif request.form['password1'] and request.form['password2']:
                        g.db.execute("UPDATE users SET password=?, su=? WHERE username=?", [hash_passwd(request.form['password1']), su, request.form['username']])
                        g.db.commit()

                    flash(u'Updated', 'success')
                else:
                    flash(u'Invalid name!', 'error')
            else:
                flash(u'No password match', 'error')
        else:
            flash(u'Unknown error!', 'error')

    users = query_db("SELECT id, name, username, su FROM users ORDER BY id ASC")
    nb_users = query_db("SELECT COUNT(id) as num FROM users", [], one=True)
    su_users = query_db("SELECT COUNT(id) as num FROM users WHERE su='Yes'", [], one=True)

    return render_template('users.html', containers=lxc.ls(), users=users, nb_users=nb_users, su_users=su_users)


@mod.route('/lwp/tokens', methods=['POST', 'GET'])
@if_logged_in()
def lwp_tokens():
    """
    returns api tokens info and get posts request: can show/delete or add token in page.
    this function uses sqlite3, require admin privilege
    """
    if session['su'] != 'Yes':
        return abort(403)

    if request.method == 'POST':
        if request.form['action'] == 'add':
            # we want to add a new token
            token = request.form['token']
            description = request.form['description']
            username = session['username']  # we should save the username due to ldap option
            g.db.execute("INSERT INTO api_tokens (username, token, description) VALUES(?, ?, ?)", [username, token, description])
            g.db.commit()
            flash(u'Token %s successfully added!' % token, 'success')


    if request.args.get('action') == 'del':
        token = request.args['token']
        g.db.execute("DELETE FROM api_tokens WHERE token=?", [token])
        g.db.commit()
        flash(u'Token %s successfully deleted!' % token, 'success')


    tokens = query_db("SELECT description, token, username FROM api_tokens ORDER BY token DESC")
    return render_template('tokens.html', tokens=tokens)


@mod.route('/checkconfig')
@if_logged_in()
def checkconfig():
    """
    returns the display of lxc-checkconfig command
    """
    if session['su'] != 'Yes':
        return abort(403)

    return render_template('checkconfig.html', containers=lxc.ls(), cfg=lxc.checkconfig())


@mod.route('/action', methods=['GET'])
@if_logged_in()
def action():
    """
    manage all actions related to containers
    lxc-start, lxc-stop, etc...
    """
    act = request.args['action']
    name = request.args['name']

    # TODO: refactor this method, it's horrible to read
    if request.args['token'] == session.get('token'):

        if act == 'start':
            try:
                if lxc.start(name) == 0:
                    time.sleep(1)  # Fix bug : "the container is randomly not displayed in overview list after a boot"
                    flash(u'Container %s started successfully!' % name, 'success')
                else:
                    flash(u'Unable to start %s!' % name, 'error')
            except lxc.ContainerAlreadyRunning:
                flash(u'Container %s is already running!' % name, 'error')
        elif act == 'stop':
            try:
                if lxc.stop(name) == 0:
                    flash(u'Container %s stopped successfully!' % name, 'success')
                else:
                    flash(u'Unable to stop %s!' % name, 'error')
            except lxc.ContainerNotRunning:
                flash(u'Container %s is already stopped!' % name, 'error')
        elif act == 'freeze':
            try:
                if lxc.freeze(name) == 0:
                    flash(u'Container %s frozen successfully!' % name, 'success')
                else:
                    flash(u'Unable to freeze %s!' % name, 'error')
            except lxc.ContainerNotRunning:
                flash(u'Container %s not running!' % name, 'error')
        elif act == 'unfreeze':
            try:
                if lxc.unfreeze(name) == 0:
                    flash(u'Container %s unfrozen successfully!' % name, 'success')
                else:
                    flash(u'Unable to unfeeze %s!' % name, 'error')
            except lxc.ContainerNotRunning:
                flash(u'Container %s not frozen!' % name, 'error')
        elif act == 'destroy':
            if session['su'] != 'Yes':
                return abort(403)
            try:
                if lxc.destroy(name) == 0:
                    flash(u'Container %s destroyed successfully!' % name, 'success')
                else:
                    flash(u'Unable to destroy %s!' % name, 'error')
            except lxc.ContainerDoesntExists:
                flash(u'The Container %s does not exists!' % name, 'error')
        elif act == 'reboot' and name == 'host':
            if session['su'] != 'Yes':
                return abort(403)
            msg = '\v*** LXC Web Panel *** \
                    \nReboot from web panel'
            try:
                subprocess.check_call('/sbin/shutdown -r now \'%s\'' % msg, shell=True)
                flash(u'System will now restart!', 'success')
            # TODO: fix blind exception handling
            except:
                flash(u'System error!', 'error')
        elif act == 'push':
            pass
    try:
        if request.args['from'] == 'edit':
            return redirect('../%s/edit' % name)
        else:
            return redirect(url_for('main.home'))
    # TODO: fix blind exception handling
    except:
        return redirect(url_for('main.home'))


@mod.route('/action/create-container', methods=['GET', 'POST'])
@if_logged_in()
def create_container():
    """
    verify all forms to create a container
    """
    if session['su'] != 'Yes':
        return abort(403)
    if request.method == 'POST':
        name = request.form['name']
        template = request.form['template']
        command = request.form['command']

        if re.match('^(?!^containers$)|[a-zA-Z0-9_-]+$', name):
            storage_method = request.form['backingstore']

            if storage_method == 'default':
                try:
                    if lxc.create(name, template=template, xargs=command) == 0:
                        flash(u'Container %s created successfully!' % name, 'success')
                    else:
                        flash(u'Failed to create %s!' % name, 'error')
                except lxc.ContainerAlreadyExists:
                    flash(u'The Container %s is already created!' % name, 'error')
                except subprocess.CalledProcessError:
                    flash(u'Error! %s' % name, 'error')

            elif storage_method == 'directory':
                directory = request.form['dir']

                if re.match('^/[a-zA-Z0-9_/-]+$', directory) and directory != '':
                    try:
                        if lxc.create(name, template=template, storage='dir --dir %s' % directory, xargs=command) == 0:
                            flash(u'Container %s created successfully!' % name, 'success')
                        else:
                            flash(u'Failed to create %s!' % name, 'error')
                    except lxc.ContainerAlreadyExists:
                        flash(u'The Container %s is already created!' % name, 'error')
                    except subprocess.CalledProcessError:
                        flash(u'Error! %s' % name, 'error')

            elif storage_method == 'zfs':
                zfs = request.form['zpoolname']

                if re.match('^[a-zA-Z0-9_-]+$', zfs) and zfs != '':
                    try:
                        if lxc.create(name, template=template, storage='zfs --zfsroot %s' % zfs, xargs=command) == 0:
                            flash(u'Container %s created successfully!' % name, 'success')
                        else:
                            flash(u'Failed to create %s!' % name, 'error')
                    except lxc.ContainerAlreadyExists:
                        flash(u'The Container %s is already created!' % name, 'error')
                    except subprocess.CalledProcessError:
                        flash(u'Error! %s' % name, 'error')

            elif storage_method == 'lvm':
                lvname = request.form['lvname']
                vgname = request.form['vgname']
                fstype = request.form['fstype']
                fssize = request.form['fssize']
                storage_options = 'lvm'

                if re.match('^[a-zA-Z0-9_-]+$', lvname) and lvname != '':
                    storage_options += ' --lvname %s' % lvname
                if re.match('^[a-zA-Z0-9_-]+$', vgname) and vgname != '':
                    storage_options += ' --vgname %s' % vgname
                if re.match('^[a-z0-9]+$', fstype) and fstype != '':
                    storage_options += ' --fstype %s' % fstype
                if re.match('^[0-9][G|M]$', fssize) and fssize != '':
                    storage_options += ' --fssize %s' % fssize

                try:
                    if lxc.create(name, template=template, storage=storage_options, xargs=command) == 0:
                        flash(u'Container %s created successfully!' % name, 'success')
                    else:
                        flash(u'Failed to create %s!' % name, 'error')
                except lxc.ContainerAlreadyExists:
                    flash(u'The container/logical volume %s is already created!' % name, 'error')
                except subprocess.CalledProcessError:
                    flash(u'Error! %s' % name, 'error')

            else:
                flash(u'Missing parameters to create container!', 'error')

        else:
            if name == '':
                flash(u'Please enter a container name!', 'error')
            else:
                flash(u'Invalid name for \"%s\"!' % name, 'error')

    return redirect(url_for('main.home'))


@mod.route('/action/clone-container', methods=['GET', 'POST'])
@if_logged_in()
def clone_container():
    """
    verify all forms to clone a container
    """
    if session['su'] != 'Yes':
        return abort(403)
    if request.method == 'POST':
        orig = request.form['orig']
        name = request.form['name']

        try:
            snapshot = request.form['snapshot']
            if snapshot == 'True':
                snapshot = True
        except KeyError:
            snapshot = False

        if re.match('^(?!^containers$)|[a-zA-Z0-9_-]+$', name):
            out = None

            try:
                out = lxc.clone(orig=orig, new=name, snapshot=snapshot)
            except lxc.ContainerAlreadyExists:
                flash(u'The Container %s already exists!' % name, 'error')
            except subprocess.CalledProcessError:
                flash(u'Can\'t snapshot a directory', 'error')

            if out and out == 0:
                flash(u'Container %s cloned into %s successfully!' % (orig, name), 'success')
            elif out and out != 0:
                flash(u'Failed to clone %s into %s!' % (orig, name), 'error')

        else:
            if name == '':
                flash(u'Please enter a container name!', 'error')
            else:
                flash(u'Invalid name for \"%s\"!' % name, 'error')

    return redirect(url_for('main.home'))


@mod.route('/action/backup-container', methods=['GET', 'POST'])
@if_logged_in()
def backup_container():
    """
    Verify the form to backup a container
    """
    if request.method == 'POST':
        container = request.form['orig']
        sr_type = request.form['dest']
        push = request.form['push']
        sr_path = None
        for sr in storage_repos:
            if sr_type in sr:
                sr_path = sr[1]
                break

        out = None

        try:
            backup_file = lxc.backup(container=container, sr_type=sr_type, destination=sr_path)
            bucket_token = get_bucket_token(container)
            if push and bucket_token and USE_BUCKET:
                    os.system('curl http://{}:{}/{} -F file=@{}'.format(BUCKET_HOST, BUCKET_PORT, bucket_token, backup_file))
        except lxc.ContainerDoesntExists:
            flash(u'The Container %s does not exist !' % container, 'error')
        except lxc.DirectoryDoesntExists:
            flash(u'Local backup directory "%s" does not exist !' % sr_path, 'error')
        except lxc.NFSDirectoryNotMounted:
            flash(u'NFS repository "%s" not mounted !' % sr_path, 'error')
        except subprocess.CalledProcessError:
            flash(u'Error during transfert !', 'error')
        except:
            flash(u'Error during transfert !', 'error')

        if out == 0:
            flash(u'Container %s backed up successfully' % container, 'success')
        elif out != 0:
            flash(u'Failed to backup %s container' % container, 'error')

    return redirect(url_for('main.home'))


@mod.route('/_refresh_cpu_host')
@if_logged_in()
def refresh_cpu_host():
    return lwp.host_cpu_percent()


@mod.route('/_refresh_uptime_host')
@if_logged_in()
def refresh_uptime_host():
    return jsonify(lwp.host_uptime())


@mod.route('/_refresh_disk_host')
@if_logged_in()
def refresh_disk_host():
    return jsonify(lwp.host_disk_usage(partition=config.get('overview', 'partition')))


@mod.route('/_refresh_memory_<name>')
@if_logged_in()
def refresh_memory_containers(name=None):
    if name == 'containers':
        containers_running = lxc.running()
        containers = []
        for container in containers_running:
            container = container.replace(' (auto)', '')
            containers.append({'name': container, 'memusg': lwp.memory_usage(container), 'settings': lwp.get_container_settings(container)})
        return jsonify(data=containers)
    elif name == 'host':
        return jsonify(lwp.host_memory_usage())
    return jsonify({'memusg': lwp.memory_usage(name)})


@mod.route('/_check_version')
@if_logged_in()
def check_version():
    return jsonify(lwp.check_version())
