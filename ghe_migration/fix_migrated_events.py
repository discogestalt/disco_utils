#!/usr/bin/env python2.7

# fix_migrated_events.py
#
# The ghe-migrator utility has an odd bug where it reverses the users
# on pull request assignment and pull request review request records
# when it imports them from github.com, and it fails to actually add
# the assignment and review request records so while the timeline shows
# the assignments and review requests, albeit reversed, the reviewers and
# assignees lists are empty. It also sets the last updated time for
# all events (comments, commits, etc.) to the time of the import, which
# messes up the user contribution history.
#
# This utility corrects the assignment and pull request review records
# so that they are shown correctly in the timeline, it adds the assignment
# and reviewer records, and it resets the last updated time so the user
# contribution history reflects the true state.
#
# 23 March 2017
# Mark Troyer <disco@blackops.io>

import MySQLdb as mysql
import argparse
import itertools
import sys


m = mysql.connect(host='localhost', db='github_enterprise')
sc = m.cursor(mysql.cursors.DictCursor)
ic = m.cursor()


class Spinner():
    spinner = itertools.cycle(['-', '\\', '|', '/'])
    def spin(self):
        sys.stdout.write(self.spinner.next())
        sys.stdout.flush()
        sys.stdout.write('\b')


def fix_assignments(guid, repo):
    sc.execute("""SELECT i.id AS issue_id, e.id AS event_id, d.id AS detail_id, i.repository_id AS repo,
i.pull_request_id AS pr, e.actor_id AS actor, d.subject_id AS subject, i.created_at AS created
FROM issue_events e
LEFT OUTER JOIN issues AS i ON i.id=e.issue_id
LEFT OUTER JOIN issue_event_details AS d ON d.issue_event_id=e.id
WHERE e.id IN (SELECT model_id FROM migratable_resources WHERE guid='{}' AND model_name='issue_event')
AND e.event='assigned' AND i.repository_id={}""".format(guid, repo))

    assignments = sc.fetchall()
    assignments_list = {}
    spinner = Spinner()

    for a in assignments:
        spinner.spin()
        assignments_list.setdefault(a['issue_id'], {})
        if a['subject'] is None:
            sc.execute("SELECT user_id FROM issues WHERE id={}".format(a['issue_id']))
            issue_user = sc.fetchone()
            a['subject'] = a['actor']
            a['actor'] = issue_user['user_id']
        if a['actor'] != a['subject']:
            ic.execute("UPDATE issue_event_details SET subject_id={} WHERE id={}".format(a['actor'], a['detail_id']))
            ic.execute("UPDATE issue_events SET actor_id={} WHERE id={}".format(a['subject'], a['event_id']))
            m.commit()
        assignments_list[a['issue_id']].setdefault(a['subject'], a['created'])

    sc.execute("""SELECT i.id AS issue_id, e.id AS event_id, d.id AS detail_id, i.repository_id AS repo,
i.pull_request_id AS pr, e.actor_id AS actor, d.subject_id AS subject, i.created_at AS created
FROM issue_events e
LEFT OUTER JOIN issues AS i ON i.id=e.issue_id
LEFT OUTER JOIN issue_event_details AS d ON d.issue_event_id=e.id
WHERE e.id IN (SELECT model_id FROM migratable_resources WHERE guid='{}' AND model_name='issue_event')
AND e.event='unassigned' AND i.repository_id={}""".format(guid, repo))

    unassignments = sc.fetchall()
    emptied = []
    for u in unassignments:
        spinner.spin()
        if u['actor'] != u['subject']:
            ic.execute("UPDATE issue_event_details SET subject_id={} WHERE id={}".format(u['actor'], u['detail_id']))
            ic.execute("UPDATE issue_events SET actor_id={} WHERE id={}".format(u['subject'], u['event_id']))
            m.commit()
        if u['subject'] in assignments_list[u['issue_id']]:
            assignments_list[u['issue_id']].pop(u['subject'], None)
            if len(assignments_list[u['issue_id']]) == 0:
                emptied.append(u['issue_id'])
    for e in emptied:
        spinner.spin()
        assignments_list.pop(e, None)

    for al in assignments_list:
        spinner.spin()
        for i in assignments_list[al]:
            ic.execute("INSERT INTO assignments (assignee_id, assignee_type, issue_id, created_at, updated_at) VALUES({0}, 'User', {1}, '{2}', '{2}')".format(i, al, assignments_list[al][i]))
            m.commit()

    print "- Done"


def fix_review_requests(guid, repo):
    sc.execute("""SELECT i.id AS issue_id, e.id AS event_id, d.id AS detail_id, i.repository_id AS repo,
i.pull_request_id AS pr, e.actor_id AS actor, d.subject_id AS subject, i.created_at AS created
FROM issue_events e
LEFT OUTER JOIN issues AS i ON i.id=e.issue_id
LEFT OUTER JOIN issue_event_details AS d ON d.issue_event_id=e.id
WHERE e.id IN (SELECT model_id FROM migratable_resources WHERE guid='{}' AND model_name='issue_event')
AND e.event='review_requested' AND i.repository_id={}""".format(guid, repo))

    review_requests = sc.fetchall()
    reviewer_list = {}
    spinner = Spinner()

    for r in review_requests:
        spinner.spin()
        reviewer_list.setdefault(r['pr'], {})
        if r['actor'] != r['subject']:
            ic.execute("UPDATE issue_event_details SET subject_id={} WHERE id={}".format(r['actor'], r['detail_id']))
            ic.execute("UPDATE issue_events SET actor_id={} WHERE id={}".format(r['subject'], r['event_id']))
            m.commit()
        reviewer_list[r['pr']].setdefault(r['actor'], r['created'])

    sc.execute("""SELECT i.id AS issue_id, e.id AS event_id, d.id AS detail_id, i.repository_id AS repo,
i.pull_request_id AS pr, e.actor_id AS actor, d.subject_id AS subject, i.created_at AS created
FROM issue_events e
LEFT OUTER JOIN issues AS i ON i.id=e.issue_id
LEFT OUTER JOIN issue_event_details AS d ON d.issue_event_id=e.id
WHERE e.id IN (SELECT model_id FROM migratable_resources WHERE guid='{}' AND model_name='issue_event')
AND e.event='review_request_removed' AND i.repository_id={}""".format(guid, repo))

    rr_removals = sc.fetchall()
    emptied = []
    for rr in rr_removals:
        spinner.spin()
        if rr['actor'] != rr['subject']:
            ic.execute("UPDATE issue_event_details SET subject_id={} WHERE id={}".format(rr['actor'], rr['detail_id']))
            ic.execute("UPDATE issue_events SET actor_id={} WHERE id={}".format(rr['subject'], rr['event_id']))
            m.commit()
        if rr['actor'] in reviewer_list[rr['pr']]:
            reviewer_list[rr['pr']].pop(rr['actor'], None)
            if len(reviewer_list[rr['pr']]) == 0:
                emptied.append(rr['pr'])
    for e in emptied:
        spinner.spin()
        reviewer_list.pop(e, None)

    for rl in reviewer_list:
        spinner.spin()
        for i in reviewer_list[rl]:
            ic.execute("INSERT INTO review_requests (reviewer_id, pull_request_id, created_at, updated_at) VALUES ({0}, {1}, '{2}', '{2}')".format(
                i,
                rl,
                reviewer_list[rl][i]
            ))
            m.commit()

    print "- Done"


def fix_timestamps(repo):
    sc.execute("SELECT id, updated_at, closed_at FROM issues WHERE repository_id={}".format(repo))
    issues = sc.fetchall()
    spinner = Spinner()

    for i in issues:
        spinner.spin()
        if i['closed_at']:
            timestamp = i['closed_at'].strftime('%s')
        else:
            timestamp = i['updated_at'].strftime('%s')
        ic.execute("UPDATE issues SET contributed_at_timestamp={}, contributed_at_offset=-28800 WHERE id={}".format(timestamp, i['id']))
        m.commit()
    sc.execute("SELECT id, created_at, merged_at FROM pull_requests where repository_id={}".format(repo))
    prs = sc.fetchall()

    for p in prs:
        spinner.spin()
        if p['merged_at']:
            updated = p['merged_at']
        else:
            updated = p['created_at']
        ic.execute("UPDATE pull_requests SET updated_at='{}', contributed_at_timestamp={}, contributed_at_offset=-28800 WHERE id={}".format(updated, updated.strftime('%s'), p['id']))
        m.commit()

    sc.execute("SELECT id, referenced_at FROM cross_references WHERE updated_at like '2017-03-10%'")
    crs = sc.fetchall()

    for c in crs:
        spinner.spin()
        ic.execute("UPDATE cross_references SET updated_at=referenced_at WHERE id={}".format(c['id']))
        m.commit()

    print "- Done"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-g',
        action='store',
        required=True,
        dest='migration_guid',
        help="The GUID of the migration you're working on as set by ghe-migrator."
    )

    args = parser.parse_args()

    sc.execute("""SELECT model_id FROM migratable_resources
WHERE guid='{}' AND model_name='repository'""".format(args.migration_guid))

    print "Loading migrated repositories"
    migrated_repos = sc.fetchall()

    for repo in migrated_repos:
        sc.execute("SELECT name FROM repositories WHERE id={}".format(repo['model_id']))
        repo_name = sc.fetchone()
        sys.stdout.write("Fixing assignments for repo {} ".format(repo_name['name']))
        fix_assignments(args.migration_guid, repo['model_id'])
        sys.stdout.write("Fixing review requests for repo {} ".format(repo_name['name']))
        fix_review_requests(args.migration_guid, repo['model_id'])
        sys.stdout.write("Fixing timestamps for repo {} ".format(repo_name['name']))
        fix_timestamps(repo['model_id'])


if __name__ == "__main__":
    sys.exit(main())
