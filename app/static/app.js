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

// The response is a file download, not a page navigation the user can watch load,
// so disable the button to make clear the click registered and stop a double-submit.
form.addEventListener("submit", () => {
  submitButton.disabled = true;
  submitButton.textContent = "Working…";
});
