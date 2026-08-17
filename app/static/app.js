"use strict";

const form = document.getElementById("scrape-form");
const submitButton = form.querySelector("button[type=submit]");
const htmlDetails = document.getElementById("html-details");
const htmlField = document.getElementById("html");

// If HTML was preserved from a rejected submission, open the <details> so the user
// sees it's still there instead of assuming it was lost and re-copying it.
if (htmlField && htmlField.value.trim()) {
  htmlDetails.open = true;
}

function showError(message) {
  const existing = document.getElementById("error-notice");
  if (existing) existing.remove();

  const notice = document.createElement("p");
  notice.id = "error-notice";
  notice.className = "notice error";
  notice.textContent = message;
  form.before(notice);
}

function clearError() {
  const existing = document.getElementById("error-notice");
  if (existing) existing.remove();
}

function downloadFilename(response) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/);
  return match ? match[1] : "recipes.zip";
}

async function errorMessageFrom(response) {
  const html = await response.text();
  const doc = new DOMParser().parseFromString(html, "text/html");
  return doc.querySelector(".notice.error")?.textContent || "Something went wrong.";
}

// A plain form POST here would either navigate to a raw JSON/HTML error body or --
// on success -- trigger a file download without navigating at all, since the response
// is `Content-Disposition: attachment`. That second case is what left the button stuck
// on "Working..." forever and made a page refresh repost the form: the browser never
// left this page, so neither the script nor the address bar ever reset. Driving the
// submit through fetch keeps the page (and its URL) exactly where it is either way, and
// this code is what resets the button once the request settles.
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  submitButton.disabled = true;
  submitButton.textContent = "Working…";

  try {
    const response = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
    });

    if (response.ok) {
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = downloadFilename(response);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } else {
      showError(await errorMessageFrom(response));
    }
  } catch (err) {
    showError(`Request failed: ${err.message}`);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Get Markdown";
  }
});
