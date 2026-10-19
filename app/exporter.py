"""CSV export of results and logs. Name/number pairs come from the frozen
campaign copy, in campaign order, so they can never be mismatched."""
import csv
import os
import time


def _stamp():
    return time.strftime("%Y%m%d_%H%M%S")


def export_results(db, folder, campaign_id=None):
    sql = ("SELECT cc.campaign_id, c.name AS campaign, cc.position, cc.name, cc.phone_e164, "
           "cc.state, cc.call_outcome, "
           "(SELECT duration_s FROM call_attempts a WHERE a.cc_id=cc.id ORDER BY a.id DESC LIMIT 1) AS call_seconds, "
           "cc.sms_state, "
           "(SELECT sent_state FROM sms_attempts s WHERE s.cc_id=cc.id ORDER BY s.id DESC LIMIT 1) AS sms_sent_state, "
           "(SELECT delivery_state FROM sms_attempts s WHERE s.cc_id=cc.id ORDER BY s.id DESC LIMIT 1) AS sms_delivery, "
           "cc.message, cc.note, cc.updated_at "
           "FROM campaign_contacts cc JOIN campaigns c ON c.id=cc.campaign_id ")
    args = []
    if campaign_id:
        sql += "WHERE cc.campaign_id=? "
        args.append(campaign_id)
    sql += "ORDER BY cc.campaign_id, cc.position"
    return _write(db.rows(sql, args), os.path.join(folder, "results_%s.csv" % _stamp()))


def export_logs(db, folder):
    rows = db.rows("SELECT ts, campaign_id, phone, event, detail FROM logs ORDER BY id")
    return _write(rows, os.path.join(folder, "logs_%s.csv" % _stamp()))


def _write(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if rows:
            w.writerow(rows[0].keys())
            for r in rows:
                # phone numbers as text so Excel keeps the leading +/0
                w.writerow([("'" + str(v) if k.startswith("phone") and v else v)
                            for k, v in zip(r.keys(), tuple(r))])
        else:
            w.writerow(["no data"])
    return path
