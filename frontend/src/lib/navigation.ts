import { useEffect, useState } from "react";

export type AppRoute =
  | { page: "projects" }
  | { page: "workspace"; projectId: string }
  | { page: "tasks" }
  | { page: "library" }
  | { page: "japanese" }
  | { page: "shadowing" }
  | { page: "system" };

export const pathFor = (route: AppRoute) => {
  if (route.page === "workspace") return `/projects/${route.projectId}`;
  if (route.page === "projects") return "/projects";
  if (route.page === "tasks") return "/tasks";
  if (route.page === "library") return "/library";
  if (route.page === "japanese") return "/learning/conversation";
  if (route.page === "shadowing") return "/learning/shadowing";
  return "/system";
};

export const parseRoute = (hash: string): AppRoute => {
  const path = hash.replace(/^#/, "") || "/projects";
  const projectMatch = path.match(/^\/projects\/([^/?#]+)/);
  if (projectMatch) return { page: "workspace", projectId: decodeURIComponent(projectMatch[1]) };
  if (path.startsWith("/tasks")) return { page: "tasks" };
  if (path.startsWith("/library")) return { page: "library" };
  if (path.startsWith("/learning/conversation")) return { page: "japanese" };
  if (path.startsWith("/learning/shadowing")) return { page: "shadowing" };
  if (path.startsWith("/system")) return { page: "system" };
  return { page: "projects" };
};

export const navigate = (route: AppRoute) => {
  window.location.hash = pathFor(route);
};

export const useAppRoute = () => {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const listener = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", listener);
    if (!window.location.hash) window.location.hash = "/projects";
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  return route;
};
