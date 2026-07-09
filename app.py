from graph import run_verification_loop


def main():
    campaign = {
        "drug": "NovaMed",
        "audience": "Adults 30-50",
        "goal": "Drug awareness",
        "message": "Educate about safe usage and encourage professional guidance",
    }

    try:
        result = run_verification_loop(campaign)
    except Exception as exc:
        print("ERROR:", type(exc).__name__, str(exc))
        return

    print("\n" + "=" * 60)
    print("DRUG EMAIL QA PROTOTYPE")
    print("=" * 60)
    print("\n[GENERATED EMAIL]")
    print(result["email"])
    print("\n[VERIFICATION SUMMARY]")
    print(f"- Passed: {result['passed']}")
    print(f"- Attempts: {result['attempts']}")
    print(f"- Overall score: {result['review']['overall_score']}")
    print(f"- Feedback: {result['review']['feedback']}")
    if result.get('image_analysis'):
        print("\n[IMAGE ANALYSIS]")
        for key, value in result['image_analysis'].items():
            print(f"- {key}: {value}")
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()