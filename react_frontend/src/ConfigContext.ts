import { createContext } from "react";

export interface FrontendConfig {
  ui: {
    api_base:              string;
    command_server_url:    string;
    ms_per_sec:            number;
    colours:               string[];
    colour_opacity_fill:   string;
    colour_opacity_border: string;
    colour_opacity_bg:     string;
  };
  system: {
    source:         string;
    snapshot_limit: number;
  };
  transport: {
    source:         string;
    snapshot_limit: number;
    initial_limit:  number;
    max_snapshots:  number;
    map: {
      centre_lat: number;
      centre_lng: number;
      zoom:       number;
    };
  };
  mobile_app: {
    source:         string;
    snapshot_limit: number;
    poll_interval:  number;
    staleness_secs: number;
  };
  aggregators: {
    list: { name: string; restart_url: string }[];
  };
}

export const ConfigContext = createContext<FrontendConfig | null>(null);
