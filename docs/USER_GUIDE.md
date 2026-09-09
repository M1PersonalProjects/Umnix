# User guide

## Sign in

Users register through `@EduAI_platform_bot`. On the WebApp login page you can
enter the Telegram ID of an existing account or choose **Sign in through Telegram
Bot**. The second option opens the bot with a one-time confirmation link. After
you confirm the account and return to the browser, the WebApp signs in
automatically. The browser remembers the session for up to 30 days. Use the
logout button to clear it and sign in with another Telegram ID.

## AI tutor

Create or open a chat, write a request, or attach a supported learning file.
Each WebApp chat is independent: another chat has another memory and another file
set. The tutor uses the latest 15 messages plus every file previously attached
to the current chat.

Book Mode can pin a textbook/page/paragraph. The tutor reads digitized database
content for the selected scope and does not mix an unrelated chat file into that
book context.

On phones the current compact tutor interface is preserved. On desktop the same
workspace fills the available screen instead of being constrained to a narrow
centered column.

## Files

Chat files can be previewed and downloaded. The file library groups stored
attachments and supports removing a file from AI memory. Access is checked on
the backend.

## Teacher assignments

Teachers create a draft, review/edit it, select students, and explicitly send it.
Student answers go to teacher review. AI may provide a review suggestion, but the
teacher records the final score/comment.

## Interactive applications

An interactive application can be opened in the isolated application view,
downloaded as HTML, versioned, and assigned to a linked student. Teachers/admins
can access answer information where authorized; students receive the learner
view without the private answer key.

## Admin textbook digitization

Open the Admin page and choose the digitization area.

1. Drop PDF files or browse for them. One ZIP may contain up to 20 PDFs.
2. Choose Preview.
3. Verify and, if needed, edit class, subject, author, and title extracted from
   the filename.
4. Choose Digitize.
5. Confirm that the textbook information has been checked.
6. Follow the sequential job progress until every page is stored.

Expected filename format:

```text
1|Mathematics|Author Name|Book Title.pdf
```

The actual values may be in Russian; the separator is the `|` character.

## Admin activity

The Activity area shows important user events together with existing chat and
file history. Search by Telegram ID to focus on one user or enter words to find
matching activity content.
