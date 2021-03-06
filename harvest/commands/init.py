from __future__ import print_function
import re
import os
import sys
import zipfile
import harvest
from ConfigParser import ConfigParser
from fabric.api import local, hide, prompt
from fabric.context_managers import lcd
from fabric.colors import red, green
from harvest import config
from harvest.decorators import cli, virtualenv
from harvest.utils import create_virtualenv, managepy_chmod

__doc__ = """\
Creates and sets up a new Harvest project.
"""

def find_replace(directory, find, replace):
    "Recursively find and replace string in files."
    for path, dirs, files in os.walk(os.path.abspath(directory)):
        for fname in files:
            fpath = os.path.join(path, fname)
            with open(fpath) as f:
                s = f.read()
            s = s.replace(find, replace)
            with open(fpath, 'w') as f:
                f.write(s)

def valid_name(name):
    if re.match(r'^[a-z_]\w*$', name, re.I) is not None:
        return True
    return False


@cli(description=__doc__)
def parser(options):
    project_name = options.project_name
    harvest_version = options.harvest_version or config.TEMPLATE_REPO_DEFAULT_VERSION
    create_env = options.create_env
    allow_input = options.allow_input
    verbosity = options.verbosity

    if not valid_name(project_name):
        print(red("Error: The project name '{0}' must be a valid Python "
            "identifier.".format(project_name)))
        sys.exit(1)

    # Ensure the name does not conflict with an existing Python module
    try:
        __import__(project_name)
        print(red("Error: The project name '{0}' conflicts with an existing "
            "Python module. Please choose another name.".format(project_name)))
        sys.exit(1)
    except ImportError:
        pass

    hidden_output = []

    if verbosity < 1:
        hidden_output.append('stdout')
    if verbosity < 2:
        hidden_output.append('running')

    print(green("Setting up project '{0}'...".format(project_name)))

    env_path = '.'
    full_env_path = None

    # Check for virtualenv
    if create_env:
        env_path = '{0}-env'.format(project_name)
        full_env_path = os.path.abspath(env_path)

    @virtualenv(full_env_path)
    def create_project(harvest_version, project_name):
        package_name = project_dir = project_name

        if os.path.exists(project_dir):
            print(red('Error: project directory already exists'))
            sys.exit(1)

        archive_url = config.TEMPLATE_ARCHIVE_URL.format(harvest_version)
        archive = config.TEMPLATE_ARCHIVE.format(harvest_version)

        download = True
        if os.path.exists(archive):
            download = prompt('{0} archive already exists. Redownload? '.format(archive),
                    default='n', validate=r'^[YyNn]$').lower()
            if download == 'n':
                download = False
            else:
                os.remove(archive)

        if download:
            print(green('- Downloading Harvest @ {0}'.format(harvest_version)))
            local('wget -O "{0}" "{1}"'.format(archive, archive_url), shell='/bin/bash')

        # Expected directory name of template
        template_dir = zipfile.ZipFile(archive).namelist()[0].rstrip('/')

        # Remove existing unarchived directory
        if os.path.exists(template_dir):
            local('rm -rf {0}'.format(template_dir), shell='/bin/bash')

        with hide(*hidden_output):
            local('unzip {0}'.format(archive), shell='/bin/bash')
            local('rm -rf {0}'.format(archive), shell='/bin/bash')

        # Rename template to project name
        local('mv {0} {1}'.format(template_dir, project_dir), shell='/bin/bash')

        # Get the template's main package name
        cparser = ConfigParser()
        cparser.read(os.path.join(project_dir, config.HARVESTRC_PATH))
        old_package_name = cparser.get('harvest', 'package')

        # Replace old package name with new one
        find_replace(project_dir, old_package_name, package_name)

        # Rename package to new name
        with lcd(project_dir):
            local('mv {0} {1}'.format(old_package_name, package_name), shell='/bin/bash')

        # Set the new package name and version
        cparser.set('harvest', 'package', package_name)
        cparser.set('harvest', 'version', template_dir.split('-')[-1])

        with lcd(project_dir):
            with open(config.HARVESTRC_PATH, 'w') as rc:
                cparser.write(rc)

    @virtualenv(full_env_path)
    def install_deps():
        print(green('- Downloading and installing dependencies'))
        local('pip install -r requirements.txt', shell='/bin/bash')

    @virtualenv(full_env_path)
    def collect_static():
        print(green('- Collecting static files'))
        local('make collect', shell='/bin/bash')

    @virtualenv(full_env_path)
    def syncdb(allow_input):
        print(green('- Setting up a SQLite database'))
        cmd = './bin/manage.py syncdb --migrate'
        if not allow_input:
            cmd += ' --noinput'
        local(cmd, shell='/bin/bash')

    with hide(*hidden_output):
        if create_env:
            create_virtualenv(env_path)

        # Create the project for the specified harvest version
        create_project(harvest_version, project_name)

        # Change into project directory for next set of commands..
        os.chdir(project_name)

        # Ensure manage.py is executable..
        managepy_chmod()

    with hide('running'):
        install_deps()

    with hide(*hidden_output):
        collect_static()

    hidden_output = ['running']
    if not allow_input:
        hidden_output.append('stdout')

    # Refrain from blocking stdout due to the prompts..
    with hide(*hidden_output):
        syncdb(allow_input)

    print(green('\nComplete! Copy and paste the following in your shell:\n'))

    if create_env:
        print(green('cd {0}/{1}\nsource ../bin/activate'.format(env_path, project_name)))
    else:
        print(green('cd {0}'.format(project_name)))

    print(green('./bin/manage.py runserver'))
    print(green('\nOpen up a web browser and go to: http://localhost:8000\n'))


parser.add_argument('project_name', help='Name of the Harvest project. This '
    'must be a valid Python identifier.')
parser.add_argument('--harvest-version', help='Harvest project version to'
    'create this project from.')
parser.add_argument('-v', '--verbosity', action='count', default=0,
    help='Increase verbosity of output.')
parser.add_argument('--no-env', action='store_false', dest='create_env',
    help='Prevents creating a virtualenv and sets up the project in the '
        'current directory.')
parser.add_argument('--no-input', action='store_false', dest='allow_input',
    help='Prevents interactive prompts during setup.')
