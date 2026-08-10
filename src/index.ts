import { Container, getContainer } from "@cloudflare/containers";

export interface Env {
	API: DurableObjectNamespace<EBankContainer>;
	DATABASE_URL: string;
	REDIS_URL: string;
	OIDC_ISSUER: string;
	OIDC_AUDIENCE: string;
	OIDC_ENABLED: string;
	IDEMPOTENCY_ENABLED: string;
	RATE_LIMIT_ENABLED: string;
	M2M_USER_FORWARD_SECRET: string;
	CORS_ORIGINS: string;
	LOG_LEVEL: string;
	ENV: string;
	LEGACY_CHALLENGE_ROUTES: string;
	WELCOME_AMOUNT: string;
	WELCOME_CURRENCY: string;
	MAX_TRANSFER_AMOUNT: string;
	MAX_WITHDRAW_AMOUNT: string;
}

function apiEnvVars(env: Env): Record<string, string> {
	return {
		DATABASE_URL: env.DATABASE_URL,
		REDIS_URL: env.REDIS_URL,
		OIDC_ENABLED: env.OIDC_ENABLED || "true",
		OIDC_ISSUER: env.OIDC_ISSUER,
		OIDC_AUDIENCE: env.OIDC_AUDIENCE || "e-bank-api",
		IDEMPOTENCY_ENABLED: env.IDEMPOTENCY_ENABLED || "true",
		RATE_LIMIT_ENABLED: env.RATE_LIMIT_ENABLED || "true",
		M2M_USER_FORWARD_SECRET: env.M2M_USER_FORWARD_SECRET || "",
		RESET_ENABLED: "false",
		LEGACY_CHALLENGE_ROUTES: env.LEGACY_CHALLENGE_ROUTES || "false",
		CORS_ORIGINS: env.CORS_ORIGINS || "https://kalke.dev,https://www.kalke.dev",
		LOG_LEVEL: env.LOG_LEVEL || "INFO",
		ENV: env.ENV || "production",
		WELCOME_AMOUNT: env.WELCOME_AMOUNT || "10000.00",
		WELCOME_CURRENCY: env.WELCOME_CURRENCY || "USD",
		MAX_TRANSFER_AMOUNT: env.MAX_TRANSFER_AMOUNT || "10000.00",
		MAX_WITHDRAW_AMOUNT: env.MAX_WITHDRAW_AMOUNT || "10000.00",
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
