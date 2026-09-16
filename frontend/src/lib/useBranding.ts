import { useApi } from "./api";

export type Branding = {
  app_name: string;
  images: { logo: boolean; login_logo: boolean; icon: boolean };
};

/* The app's name and marks.
 *
 * Readable without signing in, because the sign-in page needs the logo and the
 * browser needs the icon before anyone has.
 */
export function useBranding() {
  return useApi<Branding>("/branding");
}

export function brandingUrl(kind: keyof Branding["images"]): string {
  return `/api/branding/${kind}`;
}
