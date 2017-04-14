#!/usr/bin/env python2.7

# migrate_reviews.py
#
# Migrates pull request reviews from github.com to GitHub Enterprise.
#
# As of version 2.9.1 of GitHub Enterprise, the ghe-migrator tool
# does not yet handle migrating the pull request reviews from
# github.com repositories. It does import the pull request review
# comments, but leaves them all in "pending" state, and correcting
# that makes them appear as normal comments as the reviews they are
# associated with are not imported.
#
# It also inexplicably doesn't migrate the protection settings for
# the branches in a repository.
#
# This utility retrieves the reviews for all migrated pull requests
# and associates the comments with them properly. Note that depending
# on the number of pull requests this process can take some time as
# API calls to github.com are limited to 5000 per hour. It also retrieves
# the branch protections settings from github.com and applies them to
# the migrated versions in GitHub Enteprise.
#
# 14 April 2017
# Mark Troyer <disco@blackops.io>

import argparse
import dateutil.parser
from migration_helper import MigrationHelper
import sys
from time import sleep
import warnings

warnings.filterwarnings('ignore', message="Invalid utf8 character string")


def migrate_branch_protection(mh, repo_id, ghe_user, gh_repo):
    """
    Migrate branch protection settings for the repository.
    
    Arguments:
        repo_id (int): The local id of the repository
        ghe_user (str): Username of the person performing the migration
        gh_repo (object): GitHub repository object
    """

    user_id = mh.get_local_userid(ghe_user)
    already_protected = mh.get_protected_branches(repo_id)
    for branch in gh_repo.branches():
        if branch.name in already_protected:
            continue
        if branch.protected:
            print "Branch: {}".format(branch.name)
            mh.set_branch_protection(repo_id, user_id, branch)


def migrate_reviews(mh, repo_id, gh_repo):
    """
    Migrate all pull request reviews for a given repository from github.com
    to GitHub Enterprise

    Arguments:
        repo_id (int): The local id of the migrated repository
        gh_repo (object): GitHub repository object
    """
    # The API has a habit of returning a blank response and stopping
    # the migration process, so we'll check for already migrated
    # reviews and pick up where we left off
    last_reviewed_pr = mh.get_last_migrated_review(repo_id)

    for pr in mh.get_migrated_prs(repo_id):
        if pr['number'] <= last_reviewed_pr:
            print "- Pull request {} (id: {}) ...Already migrated, skipping".format(pr['number'], pr['id'])
            continue

        sys.stdout.write("- Pull request {} (id: {}) ".format(pr['number'], pr['id']))
        sys.stdout.flush()

        # Get the github.com version of the pull request
        gh_pr = gh_repo.pull_request(pr['number'])

        # Get all reviews attached to the pull request and extract the
        # data we need for the migration
        reviews = {}
        for rev in gh_pr.reviews():
            formatter = 'NULL'
            if len(rev.body) > 0:
                formatter = "'markdown'"
            reviews[rev.id] = {
                'pull_request_id': pr['id'],
                'user_id': mh._get_user_id(rev.user.login),
                'state': mh.review_states[rev.state],
                'head_sha': rev.commit_id,
                'body': rev.body,
                'submitted_at': dateutil.parser.parse(rev.submitted_at, ignoretz=True),
                'formatter': formatter,
                'comment_id': []
            }
        if len(reviews) == 0:
            print "...No reviews"
            sleep(1)
            continue

        # Get any review comment records that go with the pull request
        for com in gh_pr.review_comments():
            # This is a little fudge factor for testing the migration.
            # During the final migration the repositories on github.com
            # should be locked, so no updates will take place. During
            # testing the repositories won't be locked so you can easily
            # run into the situation where a comment will be added after
            # the migration archive was created and so there won't be a
            # local id for it.
            if com.pull_request_review_id:
                try:
                    reviews[com.pull_request_review_id]['comment_id'].append(mh.get_local_comment_id(com.id))
                except TypeError:
                    continue

        # Now that we have all the reviews and associated comments
        # we add the reviews to the pull_request_reviews table and
        # associated the comments with them.
        for r in reviews:
            mh.add_review(pr['number'], reviews[r], gh_pr)

            sys.stdout.write(".")
            sys.stdout.flush()
        print " Done"
        sleep(2)

    # Now that all the reviews have been migrated and the comments
    # associated, we need to set the state for the comments from
    # pending to active.
    mh.set_comments_active(repo_id)
    # Reset the repository pushed_at time back to what github.com
    # says it is to maintain a semblance of the order you see the
    # listing in there.
    mh.set_repo_pushed(repo_id, gh_repo.pushed_at.replace(tzinfo=None))


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
        '-l', '--local-user',
        action='store',
        required=True,
        dest='ghe_user',
        help="Your GitHub Enterprise username."
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
        # Get the github.com version of the repo as an object
        gh_repo = migrator.gh.repository(migrator.org, i['name'])

        print "Setting feature options for repo {}".format(i['name'])
        migrator.set_feature_options(i['id'], gh_repo.has_wiki, gh_repo.has_issues)

        print "Migrating branch protection settings for {}".format(i['name'])
        migrate_branch_protection(migrator, i['id'], args.ghe_user, gh_repo)

        print "Migrating reviews for repo {}".format(i['name'])
        migrate_reviews(migrator, i['id'], gh_repo)


if __name__ == "__main__":
    sys.exit(main())
