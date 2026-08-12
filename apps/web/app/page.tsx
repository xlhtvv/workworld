import {headers} from "next/headers";
import {redirect} from "next/navigation";

export default async function Home() {
  const language = (await headers()).get("accept-language")?.toLowerCase() ?? "en";
  redirect(language.startsWith("zh") ? "/zh" : "/en");
}
