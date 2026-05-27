import type { ExtensionAPI, ToolCallEvent } from "@earendil-works/pi-coding-agent";
import { appendFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";

function commandFrom(event: ToolCallEvent): string {
	const input = event.input;
	if (!input || typeof input !== "object") return "";
	if (!("command" in input)) return "";
	return String(input.command ?? "").trim();
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event) => {
		if (event.toolName !== "bash") return undefined;

		const command = commandFrom(event);
		const path = process.env.SIGIL_BASH_HANDOFF_PATH;
		if (path && command) {
			await mkdir(dirname(path), { recursive: true });
			await appendFile(
				path,
				`${JSON.stringify({
					version: 1,
					timestamp: new Date().toISOString(),
					toolCallId: event.toolCallId,
					toolName: event.toolName,
					command,
					input: event.input,
				})}\n`,
				"utf8",
			);
		}

		return {
			block: true,
			reason: "Bash command handed off to the terminal for user review.",
		};
	});
}
