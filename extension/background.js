importScripts("form_engine.js");
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
