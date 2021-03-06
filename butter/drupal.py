from __future__ import with_statement
from fabric.api import task, env, cd, hide, execute, settings
from fabric.operations import run, prompt
from fabric.contrib import files
from fabric.contrib import console
from urlparse import urlparse
from butter import deploy
from butter.host import pre_clean

@task
def push(ref):
    """
    Deploy a commit to a host
    """

    if env.repo_type == 'git':
        from butter import git as repo
    elif env.repo_type == 'hg':
        from butter import hg as repo
    parsed_ref = repo.check_commit(ref)
    deploy.clean()
    build_path = '%s/changesets/%s' % (env.host_site_path, parsed_ref)
    pre_clean(build_path)
    repo.checkout(parsed_ref)
    settings_php(build_path)
    set_perms(build_path)
    link_files(build_path)
    deploy.mark(parsed_ref)

@task
def setup_env():
    """
    Set up the directory structure at env.host_site_path
    """
    from fabric.api import sudo

    print('+ Creating directory structure')
    if files.exists(env.host_site_path):
        if console.confirm('Remove existing directory %s' % env.host_site_path):
            with hide('running', 'stdout'):
                run('rm -rf %s' % env.host_site_path)
        else:
            print('+ Directory not removed and recreated')
            return
    with hide('running', 'stdout'):
        run('mkdir -p %s' % env.host_site_path)
    with cd(env.host_site_path):
        with hide('running', 'stdout'):
            run('mkdir changesets files logs private')
            run('touch logs/access.log logs/error.log')
            print('+ Cloning repository: %s' % env.repo_url)
            run('%s clone %s private/repo' % (env.repo_type, env.repo_url))
            if not 'url' in env:
                env.url = prompt('Please enter the site url (ex: qa4.dev.ombuweb.com): ')
            virtual_host = 'private/%s' % env.url
            if files.exists(virtual_host):
                run('rm %s' % virtual_host)
            virtual_host_contents = """<VirtualHost *:80>

  # Admin email, Server Name (domain name) and any aliases
  ServerAdmin martin@ombuweb.com
  ServerName %%url%%

  # Index file and Document Root (where the public files are located)
  DirectoryIndex index.php
  DocumentRoot %%host_site_path%%/current

  # Custom log file locations
  ErrorLog  %%host_site_path%%/logs/error.log
  CustomLog %%host_site_path%%/logs/access.log combined

  <Directory />

    SetEnv APPLICATION_ENV %%host_type%%
    AllowOverride All

    AuthType Basic
    AuthName "Protected"
    AuthUserFile /vol/main/htpwd
    Require user dev1
    Order deny,allow
    Deny from all
    Allow from 75.145.65.101
    Satisfy any

  </Directory>

</VirtualHost>"""
            files.append(virtual_host, virtual_host_contents);
            files.sed(virtual_host, '%%host_site_path%%', env.host_site_path)
            files.sed(virtual_host, '%%host_type%%', env.host_type)
            files.sed(virtual_host, '%%url%%', env.url)
            run('rm %s.bak' % virtual_host)
            sudo('if [ ! -L /etc/apache2/sites-available/%s ]; then  ln -s %s /etc/apache2/sites-available/%s; fi' % (env.url, env.host_site_path + '/' + virtual_host, env.url))
            sudo('if [ ! -L /etc/apache2/sites-enabled/%(url)s]; then ln -s ../sites-available/%(url)s /etc/apache2/sites-enabled/%(url)s; fi' % env)
            sudo('service apache2 force-reload')
    print('+ Site directory structure created at: %s' % env.host_site_path)


def settings_php(build_path):
    print('+ Configuring site settings.php')
    with cd('%s/public/sites/default' % build_path):
        file = "settings.%s.php" % env.host_type
        if files.exists(file):
            files.sed(file, '%%DB_DB%%', env.db_db)
            files.sed(file, '%%DB_USER%%', env.db_user)
            files.sed(file, '%%DB_PW%%', env.db_pw)
            files.sed(file, '%%DB_HOST%%', env.db_host)
            if 'smtp_pw' in env:
              files.sed(file, '%%SMTP_PW%%', env.smtp_pw)
            if 'base_url' in env:
                files.sed(file, '%%BASE_URL%%', env.base_url)
            if files.exists('settings.php'):
                run('rm settings.php')
            run('cp settings.%s.php settings.php' % env.host_type )
            run('rm settings.*.php settings.*.bak')
        else:
            run('ls -lah')
            abort('Could not find %s' % file)

def set_perms(build_path):
    print('+ Setting Drupal permissions')
    with cd(env.host_site_path):
        run('chown %s:%s %s && chgrp -R %s %s' % (env.user,
            env.host_webserver_user, build_path, env.host_webserver_user,
            build_path))
        run('chmod -R 2750 %s' % build_path)
        run('chmod 0440 %s/public/sites/default/settings*' % build_path)

def link_files(build_path):
    print('+ Creating symlinks')
    if not 'files_path' in env:
        env.files_path = 'public/sites/default/files'
    with cd(build_path):
        run('rm -rf %s' % env.files_path)
        run('ln -s %s/files %s' % (env.host_site_path, env.files_path))
    with cd(env.host_site_path):
        run('if [ -h current ] ; then unlink current ; fi')
        run('ln -s %s/public current' % build_path)

@task
def sync(src, dst):
    """
    Moves drupal sites between servers
    """
    import getpass
    from fabric.api import hide
    from fabric.operations import get, put, local
    from fabric.utils import abort
    from fabric.colors import blue
    from copy import copy

    # Really make sure user wants to push to production.
    if dst == 'production':
      force_push = prompt('Are you sure you want to push to production (WARNING: this will destroy production db):', None, 'n', 'y|n')
      if force_push == 'n':
        abort('Sync aborted')

    # record the environments
    execute(dst)
    dst_env = copy(env)
    execute(src)
    src_env = copy(env)

    # helper vars
    sqldump = '/tmp/src_%s.sql.gz' % env.db_db
    src_files = '%s/current/sites/default/files/' % src_env.host_site_path

    # grab a db dump
    with settings(host_string=src_env.hosts[0]):
        run('mysqldump -u%s -p%s %s | gzip > %s' %
                (src_env.db_user, src_env.db_pw, env.db_db, sqldump))
        get(sqldump, sqldump)

    # parse src
    src_host = urlparse('ssh://' + src_env.hosts[0])

    drop_tables_sql = """mysql -u%(db_user)s -p%(db_pw)s -BNe "show tables" %(db_db)s \
        | tr '\n' ',' | sed -e 's/,$//' \
        | awk '{print "SET FOREIGN_KEY_CHECKS = 0;DROP TABLE IF EXISTS " $1 ";SET FOREIGN_KEY_CHECKS = 1;"}' \
        | mysql -u%(db_user)s -p%(db_pw)s %(db_db)s"""

    # Pulling remote to local
    if dst == 'local':
        local(drop_tables_sql % {"db_user": dst_env.db_user, "db_pw": dst_env.db_pw,
            "db_db": dst_env.db_db})
        local("gunzip -c %s | mysql -u%s -p%s -D%s" % (sqldump, dst_env.db_user,
            dst_env.db_pw, dst_env.db_db))
        local("rm %s" % sqldump)
        dst_files = dst_env.public_path + '/sites/default/files/'
        local("""rsync --human-readable --archive --backup --progress \
                --rsh='ssh -p %s' --compress %s@%s:%s %s     \
                --exclude=css --exclude=js --exclude=styles
                """ % (src_host.port, src_env.user, src_host.hostname, src_files,
                    dst_files))

    # Source and destination environments are in the same host
    elif src_env.hosts[0] == dst_env.hosts[0]:
        with settings(host_string=dst_env.hosts[0]):
            run(drop_tables_sql % {"db_user": dst_env.db_user, "db_pw": dst_env.db_pw,
                "db_db": dst_env.db_db})
            run("gunzip -c %s | mysql -u%s -p%s -D%s" % (sqldump, dst_env.db_user,
                dst_env.db_pw, dst_env.db_db))
            run("rm %s" % sqldump)
            dst_files = '%s/%s/sites/default/files/' % (dst_env.host_site_path,
                    dst_env.public_path)
            run("""rsync --human-readable --archive --backup --progress \
                    --compress %s %s \
                    --exclude=css --exclude=js --exclude=styles
                    """ % (src_files, dst_files))

    # Pulling remote to remote & remote servers are not the same host
    else:
        with settings(host_string=dst_env.hosts[0]):
            put(sqldump, sqldump)
            run(drop_tables_sql % {"db_user": dst_env.db_user, "db_pw": dst_env.db_pw,
                "db_db": dst_env.db_db})
            run("gunzip -c %s | mysql -u%s -p%s -D%s" % (sqldump, dst_env.db_user,
                dst_env.db_pw, dst_env.db_db))
            run("rm %s" % sqldump)
            dst_files = '%s/%s/sites/default/files/' % (dst_env.host_site_path,
                    dst_env.public_path)
            run("""rsync --human-readable --archive --backup --progress \
                    --rsh='ssh -p %s' --compress %s@%s:%s %s     \
                    --exclude=css --exclude=js --exclude=styles
                    """ % (src_host.port, src_env.user, src_host.hostname, src_files,
                        dst_files))

@task
def rebuild():
    """
    DEPRECATED. Use `drupal.build` instead. This task is leftin the codebase
    for compatibility with site builds that rely on reset.sh.
    """
    print('Rebuilding the site profile')
    with cd(env.host_site_path + '/current'):
        run("""sh ../private/reset.sh -d""", shell=True)

@task
def build(dev='yes'):
    """
    Build Drupal site profile (warning: this will delete your current site
    database)
    """
    print('Rebuilding the site')

    # If there's no host defined, assume localhost and run tasks locally.
    if not env.hosts:
        from fabric.operations import local
        from fabric.api import lcd
        run_function = local
        cd_function = lcd
        env.host_site_path = '.'
    else:
        run_function = run
        cd_function = cd

    with cd_function(env.host_site_path + '/' + env.public_path):
        run_function("drush si --yes %s --site-name='%s' --site-mail='%s' --account-name='%s' --account-pass='%s' --account-mail='%s'" %
                (env.site_profile, env.site_name, 'noreply@ombuweb.com', 'system', 'pass', 'noreply@ombuweb.com'))
        run_function("chmod 755 sites/default")
        run_function("chmod 644 sites/default/settings.php")
        if dev == 'yes':
            run_function("drush en -y %s" % env.dev_modules)
            run_function("drush cc all")

@task
def enforce_perms():
    from fabric.api import sudo
    print('+ Setting file permissions with sudo')
    with cd(env.host_site_path):
        sudo('chown -R %s:%s private logs && chmod 0700 private logs' %
                (env.user, env.user))
        sudo('if [ -d private/ssl ]; then chown root:admin private/ssl; fi')
        sudo('chown -R %s:%s files && chmod -R 2770 files' % (env.user,
            env.host_webserver_user))
