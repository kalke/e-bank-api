import { Container, getContainer } from "@cloudflare/containers";

export interface Env {
	API: DurableObjectNamespace<EBankContainer>;
	DATABASE_URL: string;
	REDIS_URL: string;
	OIDC_ISSUER: string;
	OIDC_AUDIENCE: string;
	OIDC_ENABLED: string;
	IDEMPOTENCY_ENABLED: string;
	CORS_ORIGINS: string;
	LOG_LEVEL: string;
	ENV: string;
}

function apiEnvVars(env: Env): Record<string, string> {
	return {
		DATABASE_URL: env.DATABASE_URL,
		REDIS_URL: env.REDIS_URL,
		OIDC_ENABLED: env.OIDC_ENABLED || "true",
		OIDC_ISSUER: env.OIDC_ISSUER,
		OIDC_AUDIENCE: env.OIDC_AUDIENCE || "e-bank-api",
		IDEMPOTENCY_ENABLED: env.IDEMPOTENCY_ENABLED || "true",
		CORS_ORIGINS: env.CORS_ORIGINS || "https://kalke.dev,https://www.kalke.dev",
		LOG_LEVEL: env.LOG_LEVEL || "INFO",
		ENV: env.ENV || "production",
	};
}

export class EBankContainer extends Container<Env> {
	defaultPort = 8000;
	sleepAfter = "10m";

	override onStart(): void {
		this.envVars = apiEnvVars(this.env);
	}
}

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const container = getContainer(env.API, "primary");
		await container.startAndWaitForPorts({
			startOptions: { envVars: apiEnvVars(env) },
			cancellationOptions: { portReadyTimeoutMS: 120_000 },
		});
		return container.fetch(request);
	},
};
