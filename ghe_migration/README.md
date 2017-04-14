# GitHub Migration Tools

These tools fix the things that the ghe-migrator tool breaks when you go from github.com to a GitHub Enterprise instance, and migrates the surprisingly large number of things that it just misses altogether.

### complete_migrations.py
- Migrates the options for whether or not a repository has the wiki or issues enabled.
- Migrates the protection settings for all the branches in a repository.
- Migrates pull request reviews.
- Associates review comments with reviews so the history is correct.
- Removes the pending flag from  pull request review comments so they show up in the history.
- Sets the pushed_at date for the repository so it reflects the actual last update time instead of the migration time.

### fix_migrated_events.py
- Corrects reversed events in a pull request timeline
- Sets the Assignees and Reviewers for a pull request
- Corrects the last updated time on issues so that users' contribution history reflects reality instead of telling you that everyone contributed everything to that point on the date of the migration.

### migration_helper.py
- Library used by `complete_migrations.py` and `recreate_forks.py` to work with github.com and GitHub Enterprise.

### recreate_forks.py
- Maps organization member usernames from github.com to their GitHub Enterprise usernames and recreates any forks they had for organization repositories.
