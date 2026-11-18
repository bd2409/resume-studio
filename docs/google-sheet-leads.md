# Leads in a Google Sheet

Every free-tool lead, new resume order and first download is added as a row.

1. Create a Google Sheet. In row 1 type: `Time (IST) | Event | Name | Email | Phone | What | Free/Paid | Source | Link`
2. Extensions → Apps Script. Delete what's there, paste this, and click Save:

```javascript
function doPost(e) {
  var d = JSON.parse(e.postData.contents);
  SpreadsheetApp.getActiveSpreadsheet().getSheets()[0].appendRow(
    [d.time, d.event, d.name, d.email, d.phone, d.what, d.price, d.source, d.link]);
  return ContentService.createTextOutput("ok");
}
```

3. Deploy → New deployment → type **Web app** → Execute as **Me**, Who has access **Anyone** → Deploy → allow access → copy the Web app URL.
4. In Render → Environment, add `SHEET_WEBHOOK_URL` = that URL.
