flowchart TD
    A["Razorpay webhooks / simulator"] --> B["Event ingestion + signature check"]
    B --> C["Recovery case store"]
    C --> D["Diagnosis + risk models"]
    D --> E["Bounded decision agent"]
    E --> F["Policy and consent gate"]
    F --> G["Razorpay / messaging actions"]
    G --> H["Outcome webhooks"]
    H --> C
    C --> I["Dashboard + audit + experiment metrics"]