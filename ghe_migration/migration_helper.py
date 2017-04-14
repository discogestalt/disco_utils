#!/usr/bin/env python2.7

# migration_helper.py
#
# Note that this library requires the latest version of the github3.py
# module, which is not yet installable via pip. Migrating the branch
# protection settings also requires fixes that are not yet merged
# into the main repository so you'll need to clone the fork at
# https://github.com/discogestalt/github3.py.git and checkout branch
# migration_fixes to successfully. It's recommended that you use this
# in a python virtual environment using `python setup.py develop`
#
# 14 April 2017
# Mark Troyer <disco@blackops.io>

import MySQLdb as mysql
import codecs
from datetime import datetime as dt
import getpass
import github3


class MigrationHelper(object):
    gh = None
    m = None
    sc = None
    ic = None
    guid = None
    org = None
    org_id = None
    review_states = {
        'COMMENTED': 1,
        'CHANGES_REQUESTED': 30,
        'APPROVED': 40,
        'DISMISSED': 50,
    }
    _user_cache = {}

    # Set up the GitHub API and MySQL connections
    def __init__(self, args):
        if 'github_token' in args:
            self.gh = github3.login(token=args.github_token)
        else:
            twofactor = None
            if args.prompt_for_password:
                passwd = ''
                while not passwd:
                    passwd = getpass('GitHub Password: ')
            else:
                passwd = args.github_password
            if args.github_two_factor:
                twofactor = self._twofa

            self.gh = github3.login(username=args.github_username, password=passwd, two_factor_callback=twofactor)
        self.m = mysql.connect(host='localhost', db='github_enterprise', charset='utf8')
        self.sc = self.m.cursor(mysql.cursors.DictCursor)
        self.ic = self.m.cursor()
        self.guid = args.migration_guid
        if args.github_org:
            self.org = args.github_org
            self.sc.execute("SELECT id FROM users WHERE login='{}'".format(self.org))
            ans = self.sc.fetchone()
            self.org_id = ans['id']
        else:
            migrated_org = self._get_migrated_organization()
            if migrated_org:
                self.org = migrated_org['login']
                self.org_id = migrated_org['id']

    def _twofa(self):
        """
        Callback function to handle 2-factor authentication
        for GitHub accounts that require it.

        Returns: (str) Access token
        """
        code = ''
        while not code:
            code = raw_input('2FA Code: ')
        return code

    def _get_user_id(self, username):
        """
        Look up and cache the local user id number for a migrated
        GitHub user account.

        Arguments:
            username (str): The github.com user name
        Returns:
             (int): The local user id number
        """
        if not username in self._user_cache:
            self.sc.execute("""SELECT model_id FROM migratable_resources
WHERE guid='{}' AND source_url='https://github.com/{}'""".format(self.guid, username))
            user_id = self.sc.fetchone()
            self._user_cache[username] = user_id['model_id']
        return self._user_cache[username]

    def _get_local_issue_event_id(self, issue_id, event_id):
        """
        Get the local id for an issue event record based on the original
        github.com issue and event ids

        Arguments:
            issue_id (int): The github.com issue id
            event_id (int): The github.com event id
        Returns:
             (int): The local issue event id
        """
        self.sc.execute("""SELECT model_id FROM migratable_resources
WHERE guid='{}' AND source_url like '%{}#event-{}'""".format(self.guid, issue_id, event_id))
        evid = self.sc.fetchone()
        return evid['model_id']

    def _get_last_row(self, table):
        """
        Get the id of the last row inserted into a table
        
        Arguments:
            table (str): The name of the table
        Returns:
            (int): The id of the last row
        """
        self.ic.execute("SELECT max(id) FROM {}".format(table))
        new_row = self.ic.fetchone()
        return new_row[0]

    def _get_migrated_organization(self):
        """
        Get the name of the migrated organization. If more than one
        organization is present in the migration resources, return
        None - the user will have to specify.
        
        Returns:
            (str): The name of the migrated organization
        """
        try:
            self.sc.execute("""SELECT id, login FROM users
WHERE id=(SELECT model_id FROM migratable_resources WHERE model_name='organization')""")
        except mysql.OperationalError:
            return None
        return self.sc.fetchone()

    def get_local_comment_id(self, comment_id):
        """
        Look up the local id for the comment record based on the original
        id from github.com

        Arguments:
            comment_id (int): The github.com id for the comment record
        Returns:
            (int): The local id for the comment record
        """
        self.sc.execute("""SELECT model_id FROM migratable_resources
WHERE guid='{}' AND source_url like '%{}'""".format(self.guid, comment_id))
        ans = self.sc.fetchone()
        return ans['model_id']

    def get_local_userid(self, username):
        """
        Get the id for a local user based on username.
        
        Arguments:
            username (str): Local username
        Returns:
            (int): User id
        """
        self.ic.execute("SELECT id FROM users WHERE login='{}'".format(username))
        userid = self.ic.fetchone()
        return userid[0]

    def get_migrated_prs(self, repo_id):
        """
        Get the list of pull requests for a given repository

        Arguments:
            repo_id (int): The id for the repository
        Returns:
            (list): The id, updated timestamp, and number for each pull request
        """
        # Reviews were added as a feature in mid-September of 2016, so any
        # pull requests that were merged before then can be safely ignored as
        # having no reviews. For extra care we're setting the cutoff at
        # 1 September 2016
        threshold = dt(2016, 9, 1, 12, 0, 0)

        self.sc.execute("""SELECT pr.id, pr.updated_at, i.number FROM pull_requests pr, issues i
WHERE pr.repository_id={} AND pr.updated_at>'{}' AND i.pull_request_id=pr.id
ORDER BY i.number""".format(repo_id, threshold.isoformat()))
        return self.sc.fetchall()

    def get_last_migrated_review(self, repo_id):
        """
        In case the process has to be restarted, we'll check for reviews
        that have already been migrated and skip those.
        
        Arguments:
            repo_id (int): The id of the repo being migrated
        Returns:
            (int): The id of the last pull request with migrated reviews for the give repo
        """
        self.ic.execute("""SELECT pull_request_id FROM pull_request_reviews
WHERE id=(SELECT max(id) FROM pull_request_reviews
WHERE pull_request_id IN (SELECT id FROM pull_requests WHERE repository_id='{}'))""".format(repo_id))
        last_reviewed_id = self.ic.fetchone()
        if last_reviewed_id:
            self.ic.execute("""SELECT number from issues WHERE pull_request_id={}""".format(last_reviewed_id[0]))
            last_reviewed_number = self.ic.fetchone()
            return last_reviewed_number[0]
        else:
            return None

    def get_migrated_repositories(self):
        """
        Get the list of migrated repositories

        Returns:
             (list): The ids of the migrated repositories
        """
        self.sc.execute("""SELECT id, name FROM repositories
WHERE id in (SELECT model_id FROM migratable_resources
WHERE guid='{}' AND model_name='repository')""".format(self.guid))
        repos = self.sc.fetchall()
        return repos

    def get_protected_branches(self, repo_id):
        self.ic.execute("SELECT name FROM protected_branches WHERE repository_id={}".format(repo_id))
        pb = []
        for row in self.ic.fetchall():
            pb.append(row[0])
        return pb

    def set_feature_options(self, repo_id, has_wiki, has_issues):
        """
        Set the options for Wiki and Issues for a given repository
    
        Arguments:
            repo_id (int): The local id of the repository
            has_wiki (bool): Whether or not the repository wiki is enabled
            has_issues (bool): Whether or not issues are enabled for the repo
        """
        self.ic.execute("""UPDATE repositories SET has_wiki={}, has_issues={}
WHERE id={}""".format('1' if has_wiki else '0',
                      '1' if has_issues else '0',
                      repo_id
                      ))
        self.m.commit()

    def set_branch_protection(self, repo_id, user_id, branch):
        """
        Set protection options for the given branch
        
        Arguments:
            repo_id (int): Local repository ID
            user_id (int): Local id of the user performing the migration
            branch (object): GitHub branch object
        """
        protection = branch.protection_full()
        sc_enforcement = 0
        sc_strict = 0
        rev_enforcement = 0
        authorized_actors = 0
        if 'required_status_checks' in protection:
            sc_enforcement = 2 if protection['required_status_checks']['include_admins'] else 1
            if protection['required_status_checks']['strict']:
                sc_strict = 1
        if 'required_pull_request_reviews' in protection:
            rev_enforcement = 2 if protection['required_pull_request_reviews']['include_admins'] else 1
        if 'restrictions' in protection:
            authorized_actors = 1
        self.ic.execute("""INSERT INTO protected_branches
(repository_id, name, created_at, updated_at, creator_id,
required_status_checks_enforcement_level, strict_required_status_checks_policy,
authorized_actors_only, pull_request_reviews_enforcement_level)
VALUES({0}, '{1}', '{2}', '{2}', {3}, {4}, {5}, {6}, {7})""".format(
            repo_id,
            branch.name,
            dt.now(),
            user_id,
            sc_enforcement,
            sc_strict,
            authorized_actors,
            rev_enforcement
        ))
        new_pb_id = self._get_last_row('protected_branches')
        if sc_enforcement:
            for c in protection['required_status_checks']['contexts']:
                self.ic.execute("""INSERT INTO required_status_checks
(protected_branch_id, context, created_at, updated_at)
VALUES({0}, '{1}', '{2}', '{2}')""".format(
                    new_pb_id,
                    c,
                    dt.now(),
                ))
        if authorized_actors:
            for team in protection['restrictions']['teams']:
                self.ic.execute("""INSERT INTO abilities
(action, actor_id, actor_type, created_at, parent_id, priority, subject_id, subject_type, updated_at)
VALUES(1, {0}, 'Team', '{1}', 0, 1, {2}, 'ProtectedBranch', '{1}')""".format(
                    team['id'],
                    dt.now(),
                    new_pb_id,
                ))
            for user in protection['restrictions']['users']:
                self.ic.execute("""INSERT INTO abilities
(action, actor_id, actor_type, created_at, parent_id, priority, subject_id, subject_type, updated_at)
VALUES(1, {0}, 'User', '{1}', 0, 1, {2}, 'ProtectedBranch', '{1}')""".format(
                    user['id'],
                    dt.now(),
                    new_pb_id,
                ))
        self.m.commit()

    def set_comments_active(self, repo_id):
        """
        Set all pull request comments for a repository to active status.
        
        Arguments:
            repo_id (int): Local repository id
        """
        self.ic.execute("""UPDATE pull_request_review_comments SET state=1
WHERE repository_id={} AND state=0""".format(repo_id))
        self.m.commit()

    def set_repo_pushed(self, repo_id, pushed_at):
        """
        Set the pushed_at timestamp for a repository.
        
        Arguments:
            repo_id (int): Local repository id
            pushed_at (datetime.datetime): Timestamp
        """
        self.ic.execute("UPDATE repositories SET pushed_at='{}' WHERE id={}".format(pushed_at, repo_id))
        self.m.commit()

    def add_review(self, pr_number, review, gh_pr):
        """
        Add the provided review to a local pull request.
        
        Arguments:
            pr_number (int): Local pull request number
            review (dict): Contents of the review
            gh_pr (github3.pulls.PullRequest): The github.com pull request object
        """
        self.ic.execute("""INSERT INTO pull_request_reviews
(pull_request_id, user_id, state, head_sha, body, created_at, updated_at, submitted_at, formatter)
VALUES({0}, {1}, {2}, '{3}', '{4}', '{5}', '{5}', '{5}', {6})""".format(
            review['pull_request_id'],
            review['user_id'],
            review['state'],
            review['head_sha'],
            self.m.escape_string(codecs.encode(review['body'], 'utf-8')),
            review['submitted_at'],
            review['formatter']
        ))
        if len(review['comment_id']) > 0:
            new_row = self._get_last_row('pull_request_reviews')
            for c in review['comment_id']:
                self.ic.execute("""UPDATE pull_request_review_comments
SET pull_request_review_id={} WHERE id={}""".format(new_row, c))
        # APPROVED and CHANGES_REQUESTED reviews need to have the
        # user removed from the review request list so that the
        # green check mark or the red x show up in the reviewers
        # list next to the name.
        if review['state'] == 30 or review['state'] == 40:
            self.sc.execute("""SELECT id, updated_at FROM review_requests
WHERE pull_request_id={} AND reviewer_id={}""".format(review['pull_request_id'], review['user_id']))
            review_request = self.sc.fetchone()
            # If the review is newer than the review request, remove the
            # user from the list. Otherwise they were requested to review
            # again after they submitted this one so we leave them alone.
            if review_request and review['submitted_at'] > review_request['updated_at']:
                self.ic.execute("DELETE FROM review_requests WHERE id={}".format(review_request['id']))
        # State 50 == DISMISSED and is a special case that requires
        # a little extra handling beyond just adding it to the
        # table.
        if review['state'] == 50:
            new_row = self._get_last_row('pull_request_reviews')
            pr_issue = gh_pr.issue()
            for e in pr_issue.events():
                if getattr(e, 'dismissed_review', False):
                    local_event = self._get_local_issue_event_id(pr_number, e.id)
                    self.ic.execute("""UPDATE issue_event_details
SET pull_request_review_state_was={}, message='{}', pull_request_review_id={}
WHERE issue_event_id={}""".format(
                        e.dismissed_review['state'],
                        self.m.escape_string(codecs.encode(e.dismissed_review['dismissal_message'], 'utf-8')),
                        new_row,
                        local_event
                    ))
        self.m.commit()

    def add_local_fork(self, user, repo_name, ghe_url):
        """
        Create a local fork of a repository for a user.
        
        Forks can only be created for the currently logged in user,
        so this function cheats something awful. It grabs the current
        password crypt for the user from the database, sets their
        crypt to the password "migr8ion", creates the fork and then
        sets the crypt back to the original. And if the user has
        two-factor auth enabled it disables that by deleting the record
        from the database before creating the fork and then adding it
        back after. Don't judge me, I know.
        
        All that is wrapped in a try/except block so that
        if something unforeseen happens the password crypt and two-factor
        settings are replaced before bailing out.
        
        Arguments:
            user (str): Local user
            repo_name (str): The repository to fork
        """
        temporary_crypt = '$2a$08$k4ctWb8QbKlZaCM0tb4/P.FDhQpZXCoa.v2tFIO25rXeOdKBPWDAe'
        # Make sure there's a local user mapped from the github.com username
        self.sc.execute("""SELECT id, login FROM users
WHERE id=(SELECT model_id FROM migratable_resources WHERE source_url like '%{}')""".format(user))
        local_user = self.sc.fetchone()
        if not local_user:
            return None

        # Get the user's password crypt and stash it away for later
        self.ic.execute("SELECT bcrypt_auth_token FROM users WHERE login='{}'".format(local_user['login']))
        original_crypt = self.ic.fetchone()

        # Replace the crypt with the one we can authenticate with.
        self.ic.execute("UPDATE users SET bcrypt_auth_token='{}' WHERE login='{}'".format(temporary_crypt, local_user['login']))

        # Check to see if the user has two-factor auth enabled, and stash away the
        # record for later if they do.
        self.sc.execute("""SELECT id, secret, recovery_secret as rs, recovery_used_bitfield as rub,
user_id, created_at as ca, updated_at as ua, sms_number as sms, delivery_method as dm,
backup_sms_number as bsms, recovery_codes_viewed as rcv, provider
FROM two_factor_credentials WHERE user_id={}""".format(local_user['id']))
        user_2fa = self.sc.fetchone()
        if user_2fa:
            self.ic.execute("DELETE FROM two_factor_credentials WHERE id={}".format(user_2fa['id']))
        self.m.commit()

        try:
            # This totally assumes a self-signed certificate
            ghe_verify = '/etc/haproxy/ssl.crt' if ghe_url.startswith('https') else None
            ghe = github3.github.GitHubEnterprise(ghe_url, verify=ghe_verify)
            # Whee, login as the migrated local user and create them up a fork
            ghe.login(local_user['login'], 'migr8ion')
            local_repo = ghe.repository(self.org, repo_name)
            local_repo.create_fork()
            ghe.session.close()

            # Reset their password crypt back to the original
            self.ic.execute("UPDATE users SET bcrypt_auth_token='{}' WHERE login='{}'".format(original_crypt[0], local_user['login']))

            # If they had two-factor auth enabled, set that back up too
            if user_2fa:
                self.ic.execute("""INSERT INTO two_factor_credentials
VALUES({}, '{}', '{}', {}, {}, '{}', '{}', {}, '{}', {}, {}, {})""".format(
                    user_2fa['id'],
                    user_2fa['secret'],
                    user_2fa['rs'],
                    user_2fa['rub'],
                    user_2fa['user_id'],
                    user_2fa['ca'],
                    user_2fa['ua'],
                    "'{}'".format(user_2fa['sms']) if user_2fa['sms'] else 'NULL',
                    user_2fa['dm'],
                    "'{}'".format(user_2fa['bsms']) if user_2fa['bsms'] else 'NULL',
                    user_2fa['rcv'],
                    "'{}'".format(user_2fa['provider']) if user_2fa['provider'] else 'NULL',
                ))
            self.m.commit()
            return local_user['login']
        except Exception as e:
            # Something bad has happened, but we can't leave the user hanging,
            # so catch the exception and set their password and two-factor
            # auth back to the original.

            # Reset their password crypt back to the original
            self.ic.execute("UPDATE users SET bcrypt_auth_token='{}' WHERE login='{}'".format(original_crypt[0], local_user['login']))

            # If they had two-factor auth enabled, set that back up too
            if user_2fa:
                self.ic.execute("""INSERT INTO two_factor_credentials
VALUES({}, '{}', '{}', {}, {}, '{}', '{}', {}, '{}', {}, {}, {})""".format(
                    user_2fa['id'],
                    user_2fa['secret'],
                    user_2fa['rs'],
                    user_2fa['rub'],
                    user_2fa['user_id'],
                    user_2fa['ca'],
                    user_2fa['ua'],
                    "'{}'".format(user_2fa['sms']) if user_2fa['sms'] else 'NULL',
                    user_2fa['dm'],
                    "'{}'".format(user_2fa['bsms']) if user_2fa['bsms'] else 'NULL',
                    user_2fa['rcv'],
                    "'{}'".format(user_2fa['provider']) if user_2fa['provider'] else 'NULL',
                ))
            self.m.commit()
            return "Unable to create fork: {}".format(e.message)
