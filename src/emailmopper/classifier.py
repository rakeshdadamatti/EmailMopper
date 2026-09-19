import json

import ollama


class EmailClassifier:
    def __init__(self, model: str = "mistral"):
        self.model = model

    def classify(self, subject: str, sender: str, body: str) -> tuple[str, str]:
        prompt = f"""Classify this email as exactly one of MARKETING, SOCIAL, CLEAN, or TRANSACTION.
    MARKETING: promotions, newsletters, advertisements, shopping updates, unsolicited bank credit-card or loan offers, refinancing offers, rewards upsells, and other sales campaigns.
    SOCIAL: social-network notifications.
    CLEAN: personal or work conversations, transaction alerts, statements, receipts, bills, account notices, security alerts, and existing loan servicing messages such as approval, disbursement, repayment, interest, documents, or account updates. A bank message is CLEAN when it reports account activity or provides a required service notice, not when it sells a product.
    TRANSACTION: payment or transaction alerts from PhonePe, Amazon Pay, Google Pay, or BHIM UPI.
    Sender: {sender}
    Subject: {subject}
    Body: {body[:600]}
    Respond only with JSON: {{"category": "MARKETING|SOCIAL|CLEAN|TRANSACTION"}}"""
        try:
            response = ollama.generate(
            model=self.model,
            prompt=prompt,
            format="json",
                options={"temperature": 0, "num_predict": 24, "num_ctx": 2048},
            )
            data = json.loads(response["response"])
            category = str(data.get("category", "")).upper()
            if category not in {"MARKETING", "SOCIAL", "CLEAN", "TRANSACTION"}:
                return "UNCLASSIFIED", "Model returned an invalid category"
            return category, str(data.get("reason", ""))
        except Exception as error:
            return "UNCLASSIFIED", f"Error during classification: {error}"
