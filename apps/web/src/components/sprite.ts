/* The icon, label and logo sprite from the design system (design/assets/js/common.js), plus two icons the product
   needs (podcast, game). Static, trusted markup: it is rendered once in the root layout and referenced with <use>. */
export const SPRITE_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>' +
  '<symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></symbol>' +
  '<symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></symbol>' +
  '<symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>' +
  '<symbol id="i-minus" viewBox="0 0 24 24"><path d="M5 12h14"/></symbol>' +
  '<symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></symbol>' +
  '<symbol id="i-chev-r" viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></symbol>' +
  '<symbol id="i-chev-d" viewBox="0 0 24 24"><path d="M5 9l7 7 7-7"/></symbol>' +
  '<symbol id="i-chev-l" viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></symbol>' +
  '<symbol id="i-arrow-r" viewBox="0 0 24 24"><path d="M4 12h15M13 6l6 6-6 6"/></symbol>' +
  '<symbol id="i-lock" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/></symbol>' +
  '<symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/><path d="M9 12l2.2 2.2L15.5 10"/></symbol>' +
  '<symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.6v.1"/></symbol>' +
  '<symbol id="i-alert" viewBox="0 0 24 24"><path d="M12 4l9.5 16.5h-19z"/><path d="M12 10v4.5"/><path d="M12 17.6v.1"/></symbol>' +
  '<symbol id="i-refresh" viewBox="0 0 24 24"><path d="M4 12a8 8 0 0114-5.3L20 9"/><path d="M20 4v5h-5"/><path d="M20 12a8 8 0 01-14 5.3L4 15"/><path d="M4 20v-5h5"/></symbol>' +
  '<symbol id="i-share" viewBox="0 0 24 24"><circle cx="6" cy="12" r="2.6"/><circle cx="18" cy="6" r="2.6"/><circle cx="18" cy="18" r="2.6"/><path d="M8.3 10.8l7.4-3.6M8.3 13.2l7.4 3.6"/></symbol>' +
  '<symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 9V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7a2 2 0 002 2h3"/></symbol>' +
  '<symbol id="i-map" viewBox="0 0 24 24"><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/></symbol>' +
  '<symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"/></symbol>' +
  '<symbol id="i-chat" viewBox="0 0 24 24"><path d="M4 5h16v11H9.5L5 20v-4H4z"/><path d="M8 9.5h8M8 12.5h5"/></symbol>' +
  '<symbol id="i-people" viewBox="0 0 24 24"><circle cx="9" cy="8.5" r="3"/><path d="M3 20c0-3.6 2.7-6 6-6s6 2.4 6 6"/><circle cx="17.5" cy="9" r="2.4"/><path d="M16.5 14.2c2.9-.2 4.8 1.8 4.8 4.8"/></symbol>' +
  '<symbol id="i-layers" viewBox="0 0 24 24"><path d="M12 3l9 5-9 5-9-5z"/><path d="M3 12.5l9 5 9-5"/></symbol>' +
  '<symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/></symbol>' +
  '<symbol id="i-calendar" viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M8 3v4M16 3v4"/></symbol>' +
  '<symbol id="i-music" viewBox="0 0 24 24"><path d="M9 18V6.5l10-2V16"/><circle cx="6.8" cy="18" r="2.4"/><circle cx="16.8" cy="16" r="2.4"/></symbol>' +
  '<symbol id="i-screen" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="13" rx="2"/><path d="M9.5 9l5 2.5-5 2.5z"/><path d="M8 21h8"/></symbol>' +
  '<symbol id="i-film" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 4v16M16 4v16M4 9h4M4 15h4M16 9h4M16 15h4"/></symbol>' +
  '<symbol id="i-tag" viewBox="0 0 24 24"><path d="M3.5 12.5V4.5h8l9 9-8 8z"/><path d="M8 8.6v.1"/></symbol>' +
  '<symbol id="i-pin" viewBox="0 0 24 24"><path d="M12 21s-6.8-5.6-6.8-11.2a6.8 6.8 0 0113.6 0C18.8 15.4 12 21 12 21z"/><circle cx="12" cy="9.8" r="2.4"/></symbol>' +
  '<symbol id="i-book" viewBox="0 0 24 24"><path d="M5 4.5h10a3 3 0 013 3V20H8a3 3 0 01-3-3z"/><path d="M5 17a3 3 0 013-3h10"/></symbol>' +
  '<symbol id="i-qr" viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2.5v2.5H14zM18 18h2v2h-2zM18 14h2M14 19v1"/></symbol>' +
  '<symbol id="i-trash" viewBox="0 0 24 24"><path d="M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13"/></symbol>' +
  '<symbol id="i-sliders" viewBox="0 0 24 24"><path d="M4 8h9M18 8h2M4 16h2M11 16h9"/><circle cx="15.5" cy="8" r="2.3"/><circle cx="8.5" cy="16" r="2.3"/></symbol>' +
  '<symbol id="i-ext" viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/></symbol>' +
  '<symbol id="i-download" viewBox="0 0 24 24"><path d="M12 4v11M7.5 11l4.5 4.5 4.5-4.5M5 20h14"/></symbol>' +
  '<symbol id="i-send" viewBox="0 0 24 24"><path d="M4 11.5L20 4l-6.2 16-2.7-6.3z"/><path d="M11.1 13.7L20 4"/></symbol>' +
  '<symbol id="i-list" viewBox="0 0 24 24"><path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6v.1M4.5 12v.1M4.5 18v.1"/></symbol>' +
  '<symbol id="i-flag" viewBox="0 0 24 24"><path d="M6 21V4M6 5h11l-2.2 4 2.2 4H6"/></symbol>' +
  '<symbol id="i-hex" viewBox="0 0 24 24"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/></symbol>' +
  '<symbol id="i-compare" viewBox="0 0 24 24"><circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/></symbol>' +
  '<symbol id="i-menu" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></symbol>' +
  '<symbol id="i-moon" viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z"/></symbol>' +
  '<symbol id="i-nouser" viewBox="0 0 24 24"><circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.6-3.4 3.2-5.5 7-5.5s6.4 2.1 7 5.5"/><path d="M4 4l16 16"/></symbol>' +
  '<symbol id="i-table" viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M3.5 10h17M3.5 14.5h17M10 5v14"/></symbol>' +
  '<symbol id="i-pause" viewBox="0 0 24 24"><path d="M8 5v14M16 5v14"/></symbol>' +
  '<symbol id="i-bolt" viewBox="0 0 24 24"><path d="M13 3L5 13.5h6L10 21l9-11h-6z"/></symbol>' +
  '<symbol id="i-gift" viewBox="0 0 24 24"><rect x="4" y="9" width="16" height="11" rx="2"/><path d="M4 13h16M12 9v11M12 9c-1-3-5-4-5-1.5C7 9 12 9 12 9zM12 9c1-3 5-4 5-1.5 0 1.5-5 1.5-5 1.5z"/></symbol>' +
  '<symbol id="lbl-measured" viewBox="0 0 16 16"><rect x="2.5" y="2.5" width="11" height="11" rx="1.6" fill="currentColor" stroke="none"/></symbol>' +
  '<symbol id="lbl-observed" viewBox="0 0 16 16"><circle cx="8" cy="8" r="5" fill="none" stroke="currentColor" stroke-width="2.2"/></symbol>' +
  '<symbol id="lbl-modelled" viewBox="0 0 16 16"><path d="M8 2.6L14 13.2H2z" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="2.2 2" stroke-linejoin="round"/></symbol>' +
  '<symbol id="logo-a" viewBox="0 0 40 40"><g fill="none" stroke-linecap="round" stroke-width="3.4"><g stroke="#f05a38" transform="translate(2 1.5)"><path d="M6 27a14 14 0 0128 0"/><path d="M11.5 27a8.5 8.5 0 0117 0"/></g><g stroke="currentColor"><path d="M4 28a16 16 0 0132 0"/><path d="M10 28a10 10 0 0120 0"/><path d="M16 28a4 4 0 018 0"/></g></g><g fill="currentColor"><circle cx="9" cy="34" r="2.1"/><circle cx="20" cy="34" r="2.1"/><circle cx="31" cy="34" r="2.1"/></g></symbol>' +
  '<symbol id="logo-b" viewBox="0 0 40 40"><g fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><path d="M4 29a16 16 0 0132 0"/><path d="M8 29a12 12 0 0124 0"/><path d="M12 29a8 8 0 0116 0"/><path d="M16 29a4 4 0 018 0"/></g><g fill="currentColor"><circle cx="9" cy="34.5" r="1.4"/><circle cx="14.5" cy="34.5" r="1.4"/><circle cx="20" cy="34.5" r="1.4"/><circle cx="25.5" cy="34.5" r="1.4"/><circle cx="31" cy="34.5" r="1.4"/></g></symbol>' +
  '<symbol id="logo-c" viewBox="0 0 40 40"><circle cx="14" cy="16" r="10" fill="#e5533a" opacity=".92"/><circle cx="26" cy="16" r="10" fill="#2b86c5" opacity=".88"/><circle cx="20" cy="26" r="10" fill="#ffd54a" opacity=".92"/><circle cx="20" cy="19" r="3.2" fill="#12332b"/></symbol>' +
  '<symbol id="i-mic" viewBox="0 0 24 24"><rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0013 0M12 18v2.5M8.5 20.5h7"/></symbol>' +
  '<symbol id="i-gamepad" viewBox="0 0 24 24"><path d="M7 8h10a4.5 4.5 0 014.4 5.4l-.7 3.2a2.4 2.4 0 01-4.1 1.1L15 16H9l-1.6 1.7a2.4 2.4 0 01-4.1-1.1l-.7-3.2A4.5 4.5 0 017 8z"/><path d="M8.5 10.8v3M7 12.3h3M15.5 11.6v.1M17.5 13v.1"/></symbol>' +
  '</defs></svg>';
