#!/usr/bin/env python2.7

# recreate_forks.py
#
# The GitHub migration tool doesn't migrate forks, understandably so,
# and it doesn't recreate the forks for the migrated users, also
# understandably so. But that doesn't mean that recreating the forks
# can't be done, so this script gets the list of forks for a
# repository on github.com, maps the user to their local GitHub
# Enterprise username, and creates the fork for them using
# migration_helper.py to do the heavy lifting.
#
# Not this this does not, and cannot, migrate the fork directly, it's
# a new fork of the repository. Any additional branches the user may
# have had in the github.com fork will need to be pushed to the
# new GitHub Enterprise fork.
#
# 14 April 2017
# Mark Troyer <disco@blackops.io>

import argparse
from migration_helper import MigrationHelper
import sys


def main():
    parser = argparse.ArgumentParser()
    userauth = parser.add_mutually_exclusive_group(required=True)
    userauth.add_argument(
        '-t', '--token',
        action='store',
        dest='github_token',
        help="GitHub OAuth token to use for authentication."
    )
    userauth.add_argument(
        '-u', '--username',
        action='store',
        dest='github_username',
        help="GitHub username."
    )
    userpass = parser.add_mutually_exclusive_group()
    userpass.add_argument(
        '-p', '--password',
        action='store',
        dest='github_password',
        help="GitHub password."
    )
    userpass.add_argument(
        '-P',
        action='store_true',
        dest='prompt_for_password',
        help="Prompt for password instead of supplying it on the command line."
    )
    parser.add_argument(
        '-2', '--two-factor',
        action='store_true',
        dest='github_two_factor',
        help="Account requires 2-Factor authentication to access GitHub."
    )
    parser.add_argument(
        '-g',
        action='store',
        required=True,
        dest='migration_guid',
        help="The GUID of the migration you're working on as set by ghe-migrator."
    )
    parser.add_argument(
        '-o', '--organization',
        action='store',
        dest='github_org',
        help="The GitHub organization being migrated."
    )
    parser.add_argument(
        '-E', '--ghe-url',
        action='store',
        required=True,
        dest='ghe_url',
        help="URL for your GitHub Enterprise instance."
    )

    args = parser.parse_args()
    if args.github_username:
        if not args.github_password and not args.prompt_for_password:
            parser.error("When using a username to login, you must use either -p to supply a password or -P to prompt for your password.")

    migrator = MigrationHelper(args)

    if not migrator.org:
        parser.error("Unable to determine migrated organization name, please specify it with the -o option.")

    migrated_repos = migrator.get_migrated_repositories()
    for i in migrated_repos:
        print "Recreating fork for repository {}".format(i['name'])
        # Get the github.com version of the repo as an object
        gh_repo = migrator.gh.repository(migrator.org, i['name'])

        for fork in gh_repo.forks():
            sys.stdout.write("User: {}".format(fork.owner.login))
            sys.stdout.flush()
            local_username = migrator.add_local_fork(fork.owner.login, i['name'], args.ghe_url)
            if local_username:
                print " ({})".format(local_username)
            else:
                print " ...Could not find local username for {}, no fork created".format(fork.owner.login)


if __name__ == "__main__":
    sys.exit(main())
