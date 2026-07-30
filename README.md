# Apple release watch

Get a push notification on your phone within minutes of Apple shipping any
software release or beta (iOS, iPadOS, macOS, watchOS, tvOS, visionOS, Xcode -
stable, RC, and beta).

How it works: every 10 minutes a GitHub Actions workflow fetches Apple's
official developer releases feed, compares it against `seen.txt`, and if
anything new appeared it pushes a notification via [ntfy](https://ntfy.sh)
and commits the updated state.

The ntfy topic name is stored as a repository secret (`NTFY_TOPIC`) so it
stays private. To receive notifications, subscribe to that topic in the ntfy
mobile app.

Notes:

- GitHub's cron is not exact - expect notifications within roughly 5-20
  minutes of a release.
- The workflow commits a monthly heartbeat (plus a commit whenever a release
  drops) so GitHub never pauses the schedule for inactivity.
- To test: Actions tab > Apple release watch > Run workflow > tick "Send a
  test notification to your phone".

