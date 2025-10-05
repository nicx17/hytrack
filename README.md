
This Python script automates the tracking of Blue Dart shipments by monitoring an email inbox for new waybill numbers. It securely loads email and server credentials from a .env file.

The script connects to an IMAP server to scan unread emails for 11-digit waybill numbers. Once found, it adds them to a persistent JSON file (active_ids.json) to keep track of all active shipments.

For each active, non-delivered waybill, the script scrapes the official Blue Dart tracking website to fetch the latest shipment status. If a new tracking event is detected or if the package is marked as "Delivered," it sends a formatted HTML email notification to a predefined recipient. The script uses a logging system to record its operations, errors, and status updates to both the console and a tracker.log file for easy monitoring and debugging. After processing, it marks the source emails as "read" to avoid redundant checks in future runs.