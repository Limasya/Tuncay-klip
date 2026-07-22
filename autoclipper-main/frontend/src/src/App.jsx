import { useState } from "react";
import { Input, Button, Select } from "@/components/ui";

export default function App() {
  const [platform, setPlatform] = useState("youtube");
  const [sourceId, setSourceId] = useState("");
  const [targetChannel, setTargetChannel] = useState("");

  const submit = async () => {
    await fetch("/config/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_platform: platform,
        source_id: sourceId,
        target_youtube_channel: targetChannel
      })
    });
    alert("Configured!");
  };

  return (
    <div className="p-8 max-w-md mx-auto">
      <h1 className="text-2xl mb-4">Auto-Clipper Setup</h1>
      <Select value={platform} onValueChange={setPlatform} className="mb-4">
        <Select.Item value="youtube">YouTube</Select.Item>
        <Select.Item value="twitch">Twitch</Select.Item>
        <Select.Item value="kick">Kick</Select.Item>
      </Select>
      <Input
        placeholder="Source Channel ID"
        value={sourceId}
        onChange={(e) => setSourceId(e.target.value)}
        className="mb-4"
      />
      <Input
        placeholder="Target YouTube Channel ID"
        value={targetChannel}
        onChange={(e) => setTargetChannel(e.target.value)}
        className="mb-4"
      />
      <Button onClick={submit}>Save Configuration</Button>
    </div>
  );
}
