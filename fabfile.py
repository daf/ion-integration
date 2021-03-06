#!/usr/bin/env python

from __future__ import with_statement
from fabric.api import *
from fabric.contrib.console import confirm
import os
import re
import sys

versionTemplates = {
      'python': '''\
#!/usr/bin/env python

# This file is auto-generated. You should not modify by hand.
from _version import Version

# VERSION !!! This is the main version !!!
version = Version('ion', %(major)s, %(minor)s, %(micro)s)
'''
    , 'java-ivy-ioncore-dev': '<info module="ioncore-java" organisation="net.ooici" revision="%(major)s.%(minor)s.%(micro)s-dev" />'
    , 'java-ivy-eoi-agents': '<info module="eoi-agents" organisation="net.ooici" revision="%(major)s.%(minor)s.%(micro)s" />'
    , 'java-ivy-proto': '<info module="ionproto" organisation="net.ooici" revision="%(major)s.%(minor)s.%(micro)s" />'
    , 'java-build': 'version=%(major)s.%(minor)s.%(micro)s'
    , 'java-build-dev': 'version=%(major)s.%(minor)s.%(micro)s-dev'
    , 'git-tag': 'v%(major)s.%(minor)s.%(micro)s'
    , 'git-message': 'Release Version %(major)s.%(minor)s.%(micro)s'
    , 'short': '%(major)s.%(minor)s.%(micro)s'
    , 'setup-py': "version = '%(major)s.%(minor)s.%(micro)s',"
    , 'setup-py-proto-equal': "'ionproto==%(major)s.%(minor)s.%(micro)s',"
    , 'setup-py-proto-greater': "'ionproto>=%(major)s.%(minor)s.%(micro)s',"
    , 'dev-cfg-equal': 'ionproto=%(major)s.%(minor)s.%(micro)s'
}


# Monkey-patch "open" to honor fabric's current directory
_old_open = open
def open(path, *args, **kwargs):
    return _old_open(os.path.join(env.lcwd, path), *args, **kwargs)

versionRe = re.compile('^(?P<major>[0-9]+)\\.(?P<minor>[0-9]+)\\.(?P<micro>[0-9]+)(?P<pre>[-0-9a-zA-Z]+)?$')
def _validateVersion(v):
    m = versionRe.match(v)
    if not m:
        raise Exception('Version must be in the format <number>.<number>.<number>[<string>]')

    valDict = m.groupdict()
    for k in ('major', 'minor', 'micro'): valDict[k] = int(valDict[k])
    valTuple = (valDict['major'], valDict['minor'], valDict['micro'])
    return valDict, valTuple

def _getNextVersion(currentVersionStr):
    cvd, cvt = _validateVersion(currentVersionStr)
    nextVersion = '%d.%d.%d' % (cvd['major'], cvd['minor'], cvd['micro'] + 1)

    versionD, versionT = prompt('Please enter the new version (current is "%s"):' % (currentVersionStr),
                     default=nextVersion, validate=_validateVersion)

    if versionT <= cvt:
        yesno = prompt('You entered "%s", which is not higher than the current ("%s") and may overwrite a previous release. Are you absolutely SURE? (y/n)' %
                       (versionTemplates['short'] % versionD, currentVersionStr), default='n') 
        if yesno != 'y':
            abort('Invalid version requested, please try again.')

    return versionD


def _getVersionInFile(filename, matchRe):
    with open(filename, 'r') as rfile:
        lines = rfile.readlines()

    currentVersionStr = None
    for linenum,line in enumerate(lines):
        m = matchRe.search(line)
        if m:
            vals = m.groupdict()
            indent, currentVersionStr, linesep = vals['indent'], vals['version'], line[-1]
            break

    if currentVersionStr is None:
        abort('Version not found in %s.' % (filename))
    versionD, versionT = _validateVersion(currentVersionStr)
    return versionD, versionT, currentVersionStr

def _replaceVersionInFile(filename, matchRe, template, versionCb):
    with open(filename, 'r') as rfile:
        lines = rfile.readlines()

    currentVersionStr = None
    for linenum,line in enumerate(lines):
        m = matchRe.search(line)
        if m:
            vals = m.groupdict()
            indent, currentVersionStr, linesep = vals['indent'], vals['version'], line[-1]
            break

    if currentVersionStr is None:
        abort('Version not found in %s.' % (filename))

    version = versionCb(currentVersionStr)
    nextVersionStr = '%s%s%s' % (indent, template % version, linesep)

    lines[linenum] = nextVersionStr
    with open(filename, 'w') as wfile:
        wfile.writelines(lines)

def _ensureClean():
    with hide('running', 'stdout', 'stderr'):
        branch = local('git name-rev --name-only HEAD', capture=True)
        if branch != 'develop':
            abort('You must be in the "develop" branch (you are in "%s").' % (branch))

        changes = local('git status -s --untracked-files=no', capture=True)

    clean = (len(changes) == 0)
    if not clean: abort('You have local git modifications, please revert or commit first.')

    commitsBehind = int(local('git rev-list ^HEAD | wc -l', capture=True).strip())
    if commitsBehind > 0:
        yesno = prompt('You are %d commits behind HEAD. Are you SURE you want to release this version? (y/n)' % (commitsBehind), default='n')
        if yesno != 'y':
            abort('Local is behind HEAD, please try again.')

    local('git fetch --tags')

def _gitTag(version):
    with hide('running', 'stdout', 'stderr'):
        remotes = local('git remote', capture=True).split()
        if len(remotes) == 0:
            abort('You have no configured git remotes.')

    branch = 'develop'
    remote = ('origin' if 'origin' in remotes else
              'ooici' if 'ooici' in remotes else
              'ooici-eoi' if 'ooici-eoi' in remotes else
              remotes[0])
    remote = prompt('Please enter the git remote to use:', default=remote)
    if not remote in remotes:
        abort('"%s" is not a configured remote.' % (remote))

    versionTag = versionTemplates['git-tag'] % version
    versionMsg = versionTemplates['git-message'] % version

    local('git commit -am "%s"' % (versionMsg))
    commit = local('git rev-parse --short HEAD', capture=True)
    local('git tag -af %s -m "%s" %s' % (versionTag, versionMsg, commit))
    local('git push %s %s' % (remote, branch))
    local('git push %s --tags' % (remote))

    print versionTag, versionMsg, commit

    return remote

def _gitForwardMaster(remote, branch='develop'):
    with hide('running', 'stdout', 'stderr'):
        branches = local('git branch', capture=True).split()
        hasMaster = 'master' in branches
        if not hasMaster:
            local('git checkout -b master %s/master' % (remote), capture=True)
            local('git checkout %s' % (branch), capture=True)

    local('git checkout master')
    local('git fetch %s' % (remote))
    local('git merge %s/master' % (remote))
    local('git merge %s' % (branch))
    local('git push %s master' % (remote))

scpUser = None
def _deploy(pkgPattern, recursive=True, subdir=''):
    host = 'amoeba.ucsd.edu'
    remotePath = '/var/www/releases%s' % (subdir)

    global scpUser
    if scpUser is None:
        scpUser = os.getlogin()
        scpUser = prompt('Please enter your amoeba login name:', default=scpUser)

    prefix = ''
    if '*' in pkgPattern:
        prefix = pkgPattern.partition('*')[0]

    recurseFlag = '-r' if recursive else ''
    files = local('find %s' % pkgPattern, capture=True).split()
    relFiles = [file[len(prefix):] for file in files]
    relFileStr = ' '.join(['%s/%s' % (remotePath, file) for file in relFiles])

    # suppress scp -p error status with a superfluous command so we can
    # continue
    local('scp %s %s %s@%s:%s' % (recurseFlag, pkgPattern, scpUser, host, remotePath))
    local('ssh %s@%s chmod 775 %s || exit 0' % (scpUser, host, relFileStr))
    local('ssh %s@%s chgrp teamlead %s || exit 0' % (scpUser, host, relFileStr))

def _showIntro():
    print '''
-------------------------------------------------------------------------------------------------------------
ION Release Script v1.0
https://confluence.oceanobservatories.org/display/CIDev/Release+Workflow

This is the release script for packaging, tagging, and pushing new versions of various ION components.
This script assumes you are in an "ion-integration" repo clone, which is a sibling of:
"ioncore-python", "ioncore-java", or "ion-object-definitions" (whichever you intend to release).

Prerequisites:
 1) You should not have any local modifications in the repo you wish to release.
 2) You should be on the "develop" branch.
 3) You should already be at the exact commit that you want to release as a new version.
 4) You should have already updated your dependent versions in config files and committed (at least locally).
-------------------------------------------------------------------------------------------------------------
'''

setupProtoRe = re.compile("(?P<indent>\s*)'ionproto[><=]=(?P<version>[^']+)'")
devProtoRe = re.compile('(?P<indent>\s*)ionproto[><=]?=(?P<version>.+)')
def python():
    with lcd(os.path.join('..', 'ion-object-definitions', 'python')):
        protoVersion = local('python setup.py --version', capture=True).strip()
        protoVersion = _validateVersion(protoVersion)

    with lcd(os.path.join('..', 'ioncore-python')):

        _showIntro()
        _ensureClean()

        with hide('running', 'stdout', 'stderr'):
            currentVersionStr = local('python setup.py --version', capture=True)

        version = _getNextVersion(currentVersionStr)
        nextVersionStr = versionTemplates['python'] % version

        with open(os.path.join('ion', 'core', 'version.py'), 'w') as versionFile:
            versionFile.write(nextVersionStr)

        # Force the ionproto version before building the package
        _replaceVersionInFile('setup.py', setupProtoRe, versionTemplates['setup-py-proto-equal'], lambda old: protoVersion[0])
        _replaceVersionInFile('development.cfg', devProtoRe, versionTemplates['dev-cfg-equal'], lambda old: protoVersion[0])

        local('python setup.py sdist')
        local('chmod -R 775 dist')

        local('git checkout setup.py')
        _deploy('dist/*.tar.gz')

        # Set the ionproto dependency before tagging
        _replaceVersionInFile('setup.py', setupProtoRe, versionTemplates['setup-py-proto-greater'], lambda old: protoVersion[0])

        remote = _gitTag(version)
        #_gitForwardMaster(remote)

class JavaVersion(object):
    def __init__(self):
        self.version = None
    def __call__(self, currentVersionStr):
        if self.version is None:
            self.version = _getNextVersion(currentVersionStr)
        return self.version

class JavaNextVersion(object):
    def __init__(self):
        self.version = None
    def __call__(self, currentVersionStr):
        if self.version is None:
            cvd, _ = _validateVersion(currentVersionStr)
            cvd['micro'] = cvd['micro'] + 1
            self.version = cvd
        return self.version

ivyRevisionRe = re.compile('(?P<indent>\s*)<info .* revision="(?P<version>[^"]+)"')
buildRevisionRe = re.compile('(?P<indent>\s*)version=(?P<version>[^\s]+)')
def java():
    with lcd(os.path.join('..', 'ioncore-java')):
        _showIntro()
        _ensureClean()

        ivyVersionD, ivyVersionT, ivyVersionS = _getVersionInFile('ivy.xml', ivyRevisionRe)
        if ivyVersionD['pre'] is not None:
            abort('Cannot release a version with suffix %s in ivy.xml.' %
                    ivyVersionD['pre'])
        buildVersionD, buildVersionT, buildVersionS  = _getVersionInFile('build.properties', buildRevisionRe)
        if buildVersionD['pre'] is not None:
            abort('Cannot release a version with suffix %s in build.properties.' %
                    buildVersionD['pre'])
        if (ivyVersionT != buildVersionT):
            abort('Versions do not match in ivy.xml and build.properties')

        local('ant ivy-publish-local')
        local('chmod -R 775 .settings/ivy-publish/')

        _deploy('.settings/ivy-publish/repository/*', subdir='/maven/repo')

        devVersion = JavaNextVersion()
        devVersion(buildVersionS)
        _replaceVersionInFile('ivy.xml', ivyRevisionRe, versionTemplates['java-ivy-ioncore-dev'], devVersion)
        _replaceVersionInFile('build.properties', buildRevisionRe, versionTemplates['java-build-dev'], devVersion)
        
        remote =  _gitTag(buildVersionD)
        # _gitForwardMaster(remote)

def javadev():
    with lcd(os.path.join('..', 'ioncore-java')):
        _showIntro()
        _ensureClean()

        local('ant ivy-publish-local')
        local('chmod -R 775 .settings/ivy-publish/')

        _deploy('.settings/ivy-publish/repository/*', subdir='/maven/repo')

def eoiagents():
    with lcd(os.path.join('..', 'eoi-agents')):
        _showIntro()
        _ensureClean()

        ivyVersionD, ivyVersionT, ivyVersionS = _getVersionInFile('ivy.xml', ivyRevisionRe)
        if ivyVersionD['pre'] is not None:
            abort('Cannot release a version with suffix %s in ivy.xml.' %
                    ivyVersionD['pre'])
        buildVersionD, buildVersionT, buildVersionS  = _getVersionInFile('build.properties', buildRevisionRe)
        if buildVersionD['pre'] is not None:
            abort('Cannot release a version with suffix %s in build.properties.' %
                    buildVersionD['pre'])
        if (ivyVersionT != buildVersionT):
            abort('Versions do not match in ivy.xml and build.properties')

        local('ant ivy-publish-local')
        local('chmod -R 775 .settings/ivy-publish/')

        _deploy('.settings/ivy-publish/repository/*', subdir='/maven/repo')

        devVersion = JavaNextVersion()
        devVersion(buildVersionS)
        _replaceVersionInFile('ivy.xml', ivyRevisionRe, versionTemplates['java-ivy-eoi-agents'], devVersion)
        _replaceVersionInFile('build.properties', buildRevisionRe, versionTemplates['java-build'], devVersion)
        
        remote =  _gitTag(buildVersionD)
        # _gitForwardMaster(remote)

setupPyRevisionRe = re.compile("(?P<indent>\s*)version = '(?P<version>[^\s]+)'")
def proto():
    with lcd(os.path.join('..', 'ion-object-definitions')):
        _showIntro()
        _ensureClean()

        version = JavaVersion()
        _replaceVersionInFile(os.path.join('python', 'setup.py'), setupPyRevisionRe, versionTemplates['setup-py'], version)
        _replaceVersionInFile('ivy.xml', ivyRevisionRe, versionTemplates['java-ivy-proto'], version)
        _replaceVersionInFile('build.properties', buildRevisionRe, versionTemplates['java-build'], version)

        local('ant ivy-publish-local')
        local('chmod -R 775 dist')
        local('chmod -R 775 .settings/ivy-publish/')

        _deploy('dist/lib/*.tar.gz')
        _deploy('.settings/ivy-publish/repository/*', subdir='/maven/repo')

        remote = _gitTag(version.version)

