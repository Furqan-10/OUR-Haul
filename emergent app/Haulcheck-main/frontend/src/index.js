import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

const root = ReactDOM.createRoot(document.getElementById("root"));

// Suppress the benign "ResizeObserver loop" warning (emitted by Radix popovers)
// which CRA's dev error overlay otherwise renders as a full-page fatal error.
const swallowResizeObserver = (e) => {
  if (e?.message && e.message.includes("ResizeObserver loop")) {
    e.stopImmediatePropagation();
  }
};
window.addEventListener("error", swallowResizeObserver);

// Register the service worker so the driver app is installable to the home screen.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
