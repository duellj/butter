from __future__ import with_statement
from fabric.api import task, env, cd
from fabric.operations import run

@task
def cc():
    if 'sites' in env:
        for site in env.sites:
            with cd('%s/current/sites/%s' % (env.host_site_path, site)):
                print('+ Running drush cc for %s' % site)
                run('drush cc all')
    else:
        print('+ Running drush cc')
        _drush('cc all')

@task
def updatedb():
    if 'sites' in env:
        for site in env.sites:
            with cd('%s/current/sites/%s' % (env.host_site_path, site)):
                print('+ Running drush updatedb for %s' % site)
                run('drush updatedb')
    else:
        print('+ Running drush updatedb')
        _drush('updatedb')

@task
def cron():
    print('+ Running drush cron')
    _drush('cron')

@task
def migrate(migrations):
    print('+ Running migrations')
    _drush('migrate-import ' + migrations)

@task
def migrate_rollback():
    print('+ Rolling back all migrations')
    _drush('migrate-rollback --all')

@task
def solrindex():
    print('+ Rebuilding Solr index')
    _drush('solr-delete-index && drush solr-mark-all && drush solr-index')

@task
def _drush(cmd):
    with cd('%s/current' % env.host_site_path):
        run('drush ' + cmd)
