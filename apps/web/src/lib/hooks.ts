"use client";

import { useQuery } from "@tanstack/react-query";
import { api, call, type S } from "./client";

export function useMe() {
  return useQuery<S["UserOut"]>({ queryKey: ["me"], queryFn: () => call(api.GET("/auth/me")), retry: false });
}

export function useHealth() {
  return useQuery<S["HealthOut"]>({ queryKey: ["health"], queryFn: () => call(api.GET("/health")), refetchInterval: 15_000, retry: false });
}

export function usePendingApprovals(enabled = true) {
  return useQuery<S["ApprovalListOut"]>({ queryKey: ["approvals"], queryFn: () => call(api.GET("/approvals")), refetchInterval: 20_000, enabled });
}
